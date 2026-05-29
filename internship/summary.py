"""月度工时汇总模块

月度统计的创建、计算、更新
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from common.feishu_api import run_cli
from .shared.bitable_ops import get_field_text, get_field_user_id, query_records, create_record, upsert_record

from .shared.config import (
    BASE_TOKEN,
    MONTHLY_SUMMARY_TABLE_ID,
    SUMMARY_DRAFT, SUMMARY_PENDING, SUMMARY_PASSED, SUMMARY_REJECTED,
)
from .attendance_ops import (
    query_records,
    get_records_by_month, get_records_by_status,
    calculate_month_attendance, calculate_attendance_days,
    FIELD_EMPLOYEE,
)
from .calendar import get_month_workdays

logger = logging.getLogger(__name__)

# ===========================================================================
# 字段名常量
# ===========================================================================

SUMMARY_EMPLOYEE = "员工"
SUMMARY_MONTH = "统计月份"
SUMMARY_EXPECTED_DAYS = "应出勤天数"
SUMMARY_ACTUAL_DAYS = "实际出勤天数"
SUMMARY_RATE = "出勤率"
SUMMARY_STATUS = "统计状态"
SUMMARY_SUBMIT_TIME = "提交时间"
SUMMARY_APPROVAL_RESULT = "审批结果"
SUMMARY_APPROVAL_TIME = "审批时间"
SUMMARY_APPROVAL_NOTE = "审批备注"
SUMMARY_WEEK_RECORDS = "关联周记录"


# ===========================================================================
# 月度统计查询
# ===========================================================================

def query_all_summaries() -> List[Dict[str, Any]]:
    """查询所有月度统计记录

    Returns:
        月度统计记录列表
    """
    field_names = [
        SUMMARY_EMPLOYEE, SUMMARY_MONTH, SUMMARY_EXPECTED_DAYS,
        SUMMARY_ACTUAL_DAYS, SUMMARY_RATE, SUMMARY_STATUS,
        SUMMARY_SUBMIT_TIME, SUMMARY_APPROVAL_RESULT, SUMMARY_APPROVAL_TIME,
        SUMMARY_APPROVAL_NOTE, SUMMARY_WEEK_RECORDS,
    ]
    return query_records(MONTHLY_SUMMARY_TABLE_ID, field_names)


def get_summary_record(employee_id: str, month: str) -> Optional[Dict[str, Any]]:
    """获取指定员工的指定月度统计

    Args:
        employee_id: 员工 open_id
        month: 月份 YYYY-MM

    Returns:
        记录字典，无则返回 None
    """
    records = query_all_summaries()

    for rec in records:
        emp = get_field_user_id(rec, SUMMARY_EMPLOYEE)
        m = get_field_text(rec, SUMMARY_MONTH)

        if emp == employee_id and m == month:
            return rec

    return None


def get_summaries_by_status(records: List[Dict[str, Any]], status: str) -> List[Dict[str, Any]]:
    """按状态筛选月度统计

    Args:
        records: 记录列表
        status: 状态值

    Returns:
        筛选后的记录列表
    """
    return [r for r in records if get_field_text(r, SUMMARY_STATUS) == status]


# ===========================================================================
# 月度统计创建
# ===========================================================================

def create_summary_record(employee_id: str, month: str,
                          expected_days: int, actual_days: float,
                          week_record_ids: List[str]) -> Optional[str]:
    """创建月度统计记录

    Args:
        employee_id: 员工 open_id
        month: 月份 YYYY-MM
        expected_days: 应出勤天数
        actual_days: 实际出勤天数
        week_record_ids: 关联的周记录ID列表

    Returns:
        记录 ID，失败返回 None
    """
    # 计算出勤率
    rate = 0.0
    if expected_days > 0:
        rate = round(actual_days / expected_days * 100, 2)

    fields = {
        SUMMARY_EMPLOYEE: employee_id,
        SUMMARY_MONTH: month,
        SUMMARY_EXPECTED_DAYS: expected_days,
        SUMMARY_ACTUAL_DAYS: actual_days,
        SUMMARY_RATE: rate,
        SUMMARY_STATUS: SUMMARY_DRAFT,
        SUMMARY_WEEK_RECORDS: json.dumps(week_record_ids) if week_record_ids else "",
    }

    payload = _make_payload(fields)
    r = run_cli("base", "+record-create", "--base-token", BASE_TOKEN,
                 "--table-id", MONTHLY_SUMMARY_TABLE_ID,
                 "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"创建月度统计失败: employee={employee_id}, month={month}")
        return None

    if isinstance(r, dict) and r.get("ok"):
        record_id = r.get("record_id")
        logger.info(f"[创建] 月度统计: employee={employee_id}, month={month}, days={actual_days}/{expected_days}, rate={rate}%")
        return record_id
    return None


def _make_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """将字段字典转为 API 负载"""
    payload: Dict[str, Any] = {}
    for fname, value in fields.items():
        if fname == SUMMARY_EMPLOYEE:
            if isinstance(value, str) and value:
                payload[fname] = [{"id": value}]
            elif isinstance(value, list):
                payload[fname] = value
        else:
            payload[fname] = value
    return payload


# ===========================================================================
# 月度汇总逻辑
# ===========================================================================

def generate_monthly_summary(month: str) -> int:
    """生成指定月份的月度汇总

    Args:
        month: 月份 YYYY-MM（如 "2024-04"）

    Returns:
        成功创建数量
    """
    logger.info(f"[月度汇总] 开始生成: {month}")

    # 解析月份
    try:
        year, m = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        logger.error(f"[月度汇总] 月份格式错误: {month}")
        return 0

    # 获取该月应出勤天数
    expected_days = get_month_workdays(year, m)
    logger.info(f"[月度汇总] 应出勤天数: {expected_days}")

    # 获取该月所有周出勤记录（已确认状态）
    all_week_records = query_all_weekly_records_with_status()
    confirmed_records = get_records_by_status(all_week_records, "已确认")
    month_records = get_records_by_month(confirmed_records, month)

    logger.info(f"[月度汇总] 周记录数: {len(month_records)}")

    # 按员工计算出勤天数
    attendance_by_emp = calculate_month_attendance(month_records, month)

    # 创建月度统计
    count = 0
    for emp_id, actual_days in attendance_by_emp.items():
        # 检查是否已存在
        existing = get_summary_record(emp_id, month)
        if existing:
            logger.info(f"[跳过] 月度统计已存在: employee={emp_id}, month={month}")
            continue

        # 获取关联的周记录ID
        week_record_ids = []
        for rec in month_records:
            if get_field_user_id(rec, FIELD_EMPLOYEE) == emp_id:
                week_record_ids.append(rec.get("_record_id", ""))

        record_id = create_summary_record(emp_id, month, expected_days, actual_days, week_record_ids)
        if record_id:
            count += 1

    logger.info(f"[月度汇总] 完成: {month}, 创建 {count} 条")
    return count


def query_all_weekly_records_with_status() -> List[Dict[str, Any]]:
    """查询所有周出勤记录（包含状态字段）"""
    from .attendance_ops import query_all_weekly_records
    return query_all_weekly_records()


# ===========================================================================
# 月度统计更新
# ===========================================================================

def update_summary_record(record_id: str, fields: Dict[str, Any]) -> bool:
    """更新月度统计记录

    Args:
        record_id: 记录 ID
        fields: 要更新的字段字典

    Returns:
        是否成功
    """
    payload = _make_payload(fields)
    r = run_cli("base", "+record-upsert", "--base-token", BASE_TOKEN,
                 "--table-id", MONTHLY_SUMMARY_TABLE_ID,
                 "--record-id", record_id,
                 "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"更新月度统计失败: record_id={record_id}")
        return False
    return r.get("ok", False) if isinstance(r, dict) else False


def update_summary_status(record_id: str, new_status: str, time_field: str = None) -> bool:
    """更新统计状态

    Args:
        record_id: 记录 ID
        new_status: 新状态
        time_field: 时间字段名（可选）

    Returns:
        是否成功
    """
    fields = {SUMMARY_STATUS: new_status}
    if time_field:
        fields[time_field] = datetime.now()
    return update_summary_record(record_id, fields)


def submit_summary(record_id: str) -> bool:
    """提交月度统计（待提交 → 待审批）

    Args:
        record_id: 记录 ID

    Returns:
        是否成功
    """
    return update_summary_status(record_id, SUMMARY_PENDING, SUMMARY_SUBMIT_TIME)


def approve_summary(record_id: str, note: str = "") -> bool:
    """审批通过月度统计

    Args:
        record_id: 记录 ID
        note: 审批备注

    Returns:
        是否成功
    """
    fields = {
        SUMMARY_STATUS: SUMMARY_PASSED,
        SUMMARY_APPROVAL_RESULT: "通过",
        SUMMARY_APPROVAL_TIME: datetime.now(),
    }
    if note:
        fields[SUMMARY_APPROVAL_NOTE] = note
    return update_summary_record(record_id, fields)


def reject_summary(record_id: str, reason: str) -> bool:
    """退回月度统计

    Args:
        record_id: 记录 ID
        reason: 退回原因

    Returns:
        是否成功
    """
    fields = {
        SUMMARY_STATUS: SUMMARY_REJECTED,
        SUMMARY_APPROVAL_RESULT: "退回",
        SUMMARY_APPROVAL_TIME: datetime.now(),
        SUMMARY_APPROVAL_NOTE: reason,
    }
    return update_summary_record(record_id, fields)


def recalculate_summary(record_id: str) -> bool:
    """重新计算月度统计（退回后修改周记录重新汇总）

    Args:
        record_id: 记录 ID

    Returns:
        是否成功
    """
    # 获取原记录信息
    summaries = query_all_summaries()
    target_record = None
    for rec in summaries:
        if rec.get("_record_id") == record_id:
            target_record = rec
            break

    if not target_record:
        logger.error(f"未找到月度统计记录: {record_id}")
        return False

    emp_id = get_field_user_id(target_record, SUMMARY_EMPLOYEE)
    month = get_field_text(target_record, SUMMARY_MONTH)

    if not emp_id or not month:
        logger.error(f"月度统计记录缺少员工或月份信息: {record_id}")
        return False

    # 重新获取周记录并计算
    try:
        year, m = int(month[:4]), int(month[5:7])
    except (ValueError, IndexError):
        logger.error(f"月份格式错误: {month}")
        return False

    expected_days = get_month_workdays(year, m)

    all_week_records = query_all_weekly_records_with_status()
    month_records = get_records_by_month(all_week_records, month)

    actual_days = 0.0
    for rec in month_records:
        if get_field_user_id(rec, FIELD_EMPLOYEE) == emp_id:
            actual_days += calculate_attendance_days(rec, month)

    # 计算出勤率
    rate = 0.0
    if expected_days > 0:
        rate = round(actual_days / expected_days * 100, 2)

    # 更新记录
    fields = {
        SUMMARY_EXPECTED_DAYS: expected_days,
        SUMMARY_ACTUAL_DAYS: actual_days,
        SUMMARY_RATE: rate,
        SUMMARY_STATUS: SUMMARY_PENDING,  # 自动回到待审批状态
        SUMMARY_APPROVAL_RESULT: "待审批",
    }

    success = update_summary_record(record_id, fields)
    if success:
        logger.info(f"[重新汇总] employee={emp_id}, month={month}, days={actual_days}/{expected_days}")
    return success


# ===========================================================================
# 获取上月月份
# ===========================================================================

def get_last_month(now: date) -> str:
    """获取上月月份字符串

    Args:
        now: 当前日期

    Returns:
        上月字符串 YYYY-MM
    """
    first_of_this_month = date(now.year, now.month, 1)
    last_month_end = first_of_this_month - timedelta(days=1)
    return last_month_end.strftime("%Y-%m")