"""实习工时扫描引擎

定时任务：
- 创建周记录：本周最后工作日 14:00
- 催办提醒：本周最后工作日 21:00
- 自动确认：每周日 23:59
- 月度汇总：每月1日 00:00
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from datetime import date, datetime, timedelta
from typing import List, Set

from .shared.config import load_app_secret
from .shared.bitable_ops import get_field_text, get_field_user_id

from .shared.config import (
    WEEKLY_ATTENDANCE_TABLE_ID, MONTHLY_SUMMARY_TABLE_ID,
    SCAN_INTERVAL_SECONDS, MAX_CONSECUTIVE_ERRORS, RETRY_DELAY_SECONDS,
    CREATE_RECORD_HOUR, CREATE_RECORD_MINUTE,
    REMIND_HOUR, REMIND_MINUTE,
    AUTO_CONFIRM_HOUR, AUTO_CONFIRM_MINUTE,
    SUMMARY_DAY, SUMMARY_HOUR, SUMMARY_MINUTE,
    STATUS_DRAFT, STATUS_PENDING, STATUS_CONFIRMED,
    SUMMARY_DRAFT, SUMMARY_REJECTED,
)
from .attendance_ops import (
    query_all_weekly_records,
    get_employee_ids_from_records,
    get_records_by_status,
    batch_create_weekly_records,
    confirm_record,
)
from .summary import (
    query_all_summaries,
    get_summaries_by_status,
    generate_monthly_summary,
    recalculate_summary,
    get_last_month,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


# ===========================================================================
# 时间判断辅助
# ===========================================================================

def get_current_week_start() -> date:
    """获取本周周一日期"""
    today = date.today()
    weekday = today.weekday()  # 周一=0, 周日=6
    return today - timedelta(days=weekday)


def get_last_workday_of_week() -> date:
    """获取本周最后工作日（周五）"""
    week_start = get_current_week_start()
    return week_start + timedelta(days=4)  # 周五


def is_time_to_create_records(now: datetime) -> bool:
    """判断是否应该创建周记录

    条件：本周最后工作日 14:00 ± 5分钟
    """
    last_workday = get_last_workday_of_week()
    target_time = datetime.combine(last_workday,
                                   datetime.time(CREATE_RECORD_HOUR, CREATE_RECORD_MINUTE))
    return abs((now - target_time).total_seconds()) < 300


def is_time_to_remind(now: datetime) -> bool:
    """判断是否应该发送催办

    条件：本周最后工作日 21:00 ± 5分钟
    """
    last_workday = get_last_workday_of_week()
    target_time = datetime.combine(last_workday,
                                   datetime.time(REMIND_HOUR, REMIND_MINUTE))
    return abs((now - target_time).total_seconds()) < 300


def is_time_to_auto_confirm(now: datetime) -> bool:
    """判断是否应该自动确认

    条件：每周日 23:59 ± 5分钟
    """
    if now.weekday() != 6:  # 周日=6
        return False
    target_time = datetime.combine(now.date(),
                                   datetime.time(AUTO_CONFIRM_HOUR, AUTO_CONFIRM_MINUTE))
    return abs((now - target_time).total_seconds()) < 300


def is_time_to_monthly_summary(now: datetime) -> bool:
    """判断是否应该生成月度汇总

    条件：每月1日 00:00 ± 5分钟
    """
    if now.day != SUMMARY_DAY:
        return False
    target_time = datetime.combine(now.date(),
                                   datetime.time(SUMMARY_HOUR, SUMMARY_MINUTE))
    return abs((now - target_time).total_seconds()) < 300


# ===========================================================================
# 任务执行
# ===========================================================================

def task_create_weekly_records() -> None:
    """任务：创建本周出勤记录"""
    logger.info("[任务] 创建周记录")

    week_start = get_current_week_start()
    logger.info(f"  → 本周: {week_start}")

    # 获取已有记录中的员工（离职员工不再创建）
    # 同时也从上月统计中获取在职员工
    existing_records = query_all_weekly_records()
    summaries = query_all_summaries()

    # 合并所有已知员工
    all_employees = get_employee_ids_from_records(existing_records)

    # 从上月统计中也提取员工（确保新员工也能被覆盖）
    for rec in summaries:
        emp_id = get_field_user_id(rec, "员工")
        if emp_id:
            all_employees.add(emp_id)

    if not all_employees:
        logger.warning("  → 无在职员工，跳过创建")
        return

    logger.info(f"  → 员工数: {len(all_employees)}")
    batch_create_weekly_records(list(all_employees), week_start)


def task_send_reminders() -> None:
    """任务：发送催办提醒"""
    logger.info("[任务] 发送催办")

    records = query_all_weekly_records()
    draft_records = get_records_by_status(records, STATUS_DRAFT)

    if not draft_records:
        logger.info("  → 无待填写记录")
        return

    logger.info(f"  → 待填写: {len(draft_records)} 条")

    # TODO: 实现飞书消息发送
    # 目前仅记录日志
    for rec in draft_records:
        emp_id = get_field_user_id(rec, "员工")
        logger.info(f"  [催办] employee={emp_id}")

    logger.info(f"[催办完成] {len(draft_records)} 条")


def task_auto_confirm() -> None:
    """任务：自动确认周记录"""
    logger.info("[任务] 自动确认")

    records = query_all_weekly_records()
    pending_records = get_records_by_status(records, STATUS_PENDING)

    if not pending_records:
        logger.info("  → 无待确认记录")
        return

    logger.info(f"  → 待确认: {len(pending_records)} 条")

    count = 0
    for rec in pending_records:
        record_id = rec.get("_record_id", "")
        if confirm_record(record_id):
            count += 1

    logger.info(f"[自动确认完成] {count}/{len(pending_records)} 条")


def task_monthly_summary() -> None:
    """任务：生成月度汇总"""
    logger.info("[任务] 月度汇总")

    # 汇总上月
    last_month = get_last_month(date.today())
    logger.info(f"  → 上月: {last_month}")

    count = generate_monthly_summary(last_month)
    logger.info(f"[月度汇总完成] {last_month}: {count} 条")


def task_check_rejected_summaries() -> None:
    """任务：检查已退回的统计（退回后修改需重新汇总）"""
    logger.info("[任务] 检查退回统计")

    summaries = query_all_summaries()
    rejected = get_summaries_by_status(summaries, SUMMARY_REJECTED)

    if not rejected:
        logger.info("  → 无已退回统计")
        return

    logger.info(f"  → 已退回: {len(rejected)} 条")

    # 检查是否有修改后需要重新汇总的
    # 注：此处逻辑需要在员工修改统计后触发重新汇总
    # 当前设计：员工修改月度统计后自动触发重新汇总
    # 此处仅记录日志
    for rec in rejected:
        record_id = rec.get("_record_id", "")
        month = get_field_text(rec, "统计月份")
        logger.info(f"  [退回] record_id={record_id}, month={month}")


# ===========================================================================
# 扫描周期
# ===========================================================================

def scan_cycle() -> None:
    """执行一次完整扫描"""
    now = datetime.now()

    logger.info("=" * 60)
    logger.info(f"[扫描] {now.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # 检查各定时任务
    if is_time_to_create_records(now):
        task_create_weekly_records()

    if is_time_to_remind(now):
        task_send_reminders()

    if is_time_to_auto_confirm(now):
        task_auto_confirm()

    if is_time_to_monthly_summary(now):
        task_monthly_summary()

    # 每次扫描都检查退回状态
    task_check_rejected_summaries()

    logger.info(f"[扫描完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


# ===========================================================================
# 主入口
# ===========================================================================

def main() -> None:
    """主入口"""
    load_app_secret()

    logger.info("=" * 60)
    logger.info("实习工时扫描引擎启动")
    logger.info(f"扫描间隔: {SCAN_INTERVAL_SECONDS}s (5分钟)")
    logger.info(f"周出勤表: {WEEKLY_ATTENDANCE_TABLE_ID}")
    logger.info(f"月度统计表: {MONTHLY_SUMMARY_TABLE_ID}")
    logger.info("=" * 60)

    # 首次扫描
    scan_cycle()

    consecutive_errors = 0

    while True:
        logger.info(f"\n[等待] {SCAN_INTERVAL_SECONDS}s 后下次扫描...")
        time.sleep(SCAN_INTERVAL_SECONDS)

        try:
            scan_cycle()
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"[ERROR] 扫描异常 ({consecutive_errors}/{MAX_CONSECUTIVE_ERRORS}): {e}")
            traceback.print_exc()

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.critical(f"[FATAL] 连续 {MAX_CONSECUTIVE_ERRORS} 次异常，终止进程")
                sys.exit(1)

            logger.warning(f"[WARN] 等待 {RETRY_DELAY_SECONDS}s 后重试")
            time.sleep(RETRY_DELAY_SECONDS)


if __name__ == "__main__":
    main()