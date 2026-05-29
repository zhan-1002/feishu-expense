"""
费用报销扫描引擎

每 5 分钟扫描报销单表，自动推进状态流转。
"""

from __future__ import annotations

import logging
import sys
import time
import traceback
from datetime import datetime
from typing import Any, Dict, List

from shared.config import (
    BASE_TOKEN,
    EXPENSE_TABLE_ID,
    load_app_secret,
)
from shared.bitable_ops import (
    STATUS_DRAFT, STATUS_PENDING, STATUS_PASSED, STATUS_REJECTED,
    APPROVAL_PENDING, APPROVAL_PASSED, APPROVAL_REJECTED,
    query_all_expenses,
    update_status,
    get_field_text,
    get_field_user_id,
    has_field_value,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ===========================================================================
# 常量定义
# ===========================================================================

SCAN_INTERVAL_SECONDS = 300  # 5 分钟扫描间隔
MAX_CONSECUTIVE_ERRORS = 3    # 最大连续错误次数
RETRY_DELAY_SECONDS = 30     # 重试等待时间


# ===========================================================================
# 阶段处理
# ===========================================================================

def process_draft(records: List[Dict[str, Any]]) -> int:
    """处理待提交状态：待提交 → 待审批

    Args:
        records: 所有报销单记录

    Returns:
        推进的记录数
    """
    draft_records = [r for r in records if get_field_text(r, "报销状态") == STATUS_DRAFT]

    if not draft_records:
        logger.info("[阶段] 待提交: 0 条")
        return 0

    count = 0
    for r in draft_records:
        rid = r.get("_record_id", "")
        summary = get_field_text(r, "报销摘要") or rid

        # 检查必填字段：报销人、报销金额、报销摘要
        if not has_field_value(r, "报销人"):
            logger.info(f"  [待提交-跳过] {summary}: 报销人为空")
            continue
        if not has_field_value(r, "报销金额"):
            logger.info(f"  [待提交-跳过] {summary}: 报销金额为空")
            continue
        if not has_field_value(r, "报销摘要"):
            logger.info(f"  [待提交-跳过] {summary}: 报销摘要为空")
            continue

        # 推进到待审批
        ok = update_status(rid, STATUS_PENDING)
        if ok:
            logger.info(f"  [待提交→待审批] {summary}")
            count += 1

    logger.info(f"[阶段] 待提交: {count}/{len(draft_records)} 条推进")
    return count


def process_pending(records: List[Dict[str, Any]]) -> tuple[int, int]:
    """处理待审批状态：待审批 → 已通过/已拒绝

    Args:
        records: 所有报销单记录

    Returns:
        (通过数, 拒绝数)
    """
    pending_records = [r for r in records if get_field_text(r, "报销状态") == STATUS_PENDING]

    if not pending_records:
        logger.info("[阶段] 待审批: 0 条")
        return 0, 0

    passed_count = 0
    rejected_count = 0

    for r in pending_records:
        rid = r.get("_record_id", "")
        summary = get_field_text(r, "报销摘要") or rid
        approval = get_field_text(r, "财务审批")

        if approval == APPROVAL_PASSED:
            ok = update_status(rid, STATUS_PASSED)
            if ok:
                logger.info(f"  [待审批→已通过] {summary}")
                passed_count += 1

        elif approval == APPROVAL_REJECTED:
            ok = update_status(rid, STATUS_REJECTED)
            if ok:
                logger.info(f"  [待审批→已拒绝] {summary}")
                rejected_count += 1

    logger.info(f"[阶段] 待审批: 通过 {passed_count} 条, 拒绝 {rejected_count} 条")
    return passed_count, rejected_count


# ===========================================================================
# 主循环
# ===========================================================================

def scan_cycle() -> None:
    """执行一次完整扫描"""
    logger.info("=" * 60)
    logger.info(f"[扫描] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    logger.info("[查询] 报销单表...")
    records = query_all_expenses()
    logger.info(f"  → {len(records)} 条记录")

    if not records:
        logger.info(f"[扫描完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        return

    # 处理各阶段
    logger.info("[阶段] 待提交...")
    process_draft(records)

    logger.info("[阶段] 待审批...")
    process_pending(records)

    logger.info(f"[扫描完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main() -> None:
    """主入口"""
    load_app_secret()

    logger.info("=" * 60)
    logger.info("费用报销扫描引擎启动")
    logger.info(f"扫描间隔: {SCAN_INTERVAL_SECONDS}s (5分钟)")
    logger.info(f"报销单表: {EXPENSE_TABLE_ID}")
    logger.info("=" * 60)

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