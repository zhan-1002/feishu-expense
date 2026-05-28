"""
费用报销扫描引擎

每 5 分钟扫描报销单表，自动推进状态流转。
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from typing import Dict, List

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
    _field_text, _field_user_id,
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

SCAN_INTERVAL = 300  # 5 分钟扫描间隔

# ===========================================================================
# 字段提取辅助
# ===========================================================================

def _text(record: dict, field_name: str) -> str:
    return _field_text([record.get(field_name)], [field_name], field_name)

def _user(record: dict, field_name: str) -> str:
    return _field_user_id([record.get(field_name)], [field_name], field_name)

def _has(record: dict, field_name: str) -> bool:
    val = record.get(field_name)
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, list):
        return len(val) > 0
    if isinstance(val, (int, float)):
        return True
    return bool(val)

# ===========================================================================
# 阶段处理
# ===========================================================================

def process_draft(records: List[dict]) -> None:
    """待提交 → 待审批"""
    draft_records = [r for r in records if _text(r, "报销状态") == STATUS_DRAFT]

    if not draft_records:
        logger.info("[阶段] 待提交: 0 条")
        return

    count = 0
    for r in draft_records:
        rid = r["_record_id"]
        summary = _text(r, "报销摘要") or rid

        # 检查必填字段：报销人、报销金额、报销摘要
        if not _has(r, "报销人"):
            logger.info(f"  [待提交-跳过] {summary}: 报销人为空")
            continue
        if not _has(r, "报销金额"):
            logger.info(f"  [待提交-跳过] {summary}: 报销金额为空")
            continue
        if not _has(r, "报销摘要"):
            logger.info(f"  [待提交-跳过] {summary}: 报销摘要为空")
            continue

        # 推进到待审批
        ok = update_status(rid, STATUS_PENDING)
        if ok:
            logger.info(f"  [待提交→待审批] {summary}")
            count += 1

    logger.info(f"[阶段] 待提交: {count}/{len(draft_records)} 条推进")


def process_pending(records: List[dict]) -> None:
    """待审批 → 已通过/已拒绝"""
    pending_records = [r for r in records if _text(r, "报销状态") == STATUS_PENDING]

    if not pending_records:
        logger.info("[阶段] 待审批: 0 条")
        return

    passed_count = 0
    rejected_count = 0

    for r in pending_records:
        rid = r["_record_id"]
        summary = _text(r, "报销摘要") or rid
        approval = _text(r, "财务审批")

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


# ===========================================================================
# 主循环
# ===========================================================================

def scan_cycle() -> None:
    """执行一次完整扫描"""

    logger.info("=" * 60)
    logger.info(f"[扫描] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    logger.info("[查询] 报销单表…")
    records = query_all_expenses()
    logger.info(f"  → {len(records)} 条记录")

    if not records:
        return

    # 处理各阶段
    logger.info("[阶段] 待提交…")
    process_draft(records)

    logger.info("[阶段] 待审批…")
    process_pending(records)

    logger.info(f"[扫描完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main() -> None:
    load_app_secret()

    logger.info("=" * 60)
    logger.info("费用报销扫描引擎启动")
    logger.info(f"扫描间隔: {SCAN_INTERVAL}s (5分钟)")
    logger.info(f"报销单表: {EXPENSE_TABLE_ID}")
    logger.info("=" * 60)

    scan_cycle()

    consecutive_errors = 0
    max_consecutive_errors = 3

    while True:
        logger.info(f"\n[等待] {SCAN_INTERVAL}s 后下次扫描…")
        time.sleep(SCAN_INTERVAL)
        try:
            scan_cycle()
            consecutive_errors = 0
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"[ERROR] 扫描异常 ({consecutive_errors}/{max_consecutive_errors}): {e}")

            import traceback
            traceback.print_exc()

            if consecutive_errors >= max_consecutive_errors:
                logger.critical(f"[FATAL] 连续 {max_consecutive_errors} 次异常，终止进程")
                sys.exit(1)

            logger.warning(f"[WARN] 等待 30s 后重试")
            time.sleep(30)


if __name__ == "__main__":
    main()