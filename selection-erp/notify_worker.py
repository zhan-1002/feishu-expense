"""
通知发送 Worker — 扫描通知队列表，通过 Bot 发送消息到群（Linux 版）

替代飞书 workflow 的通知发送功能。
可独立运行，也可在 scan_cycle 末尾调用 flush_pending_notifications()。
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.config import (
    BASE_TOKEN,
    NOTIFY_TABLE_ID,
    NOTIFY_GROUP_CHAT_ID,
)
from shared.bitable_ops import (
    query_records,
    upsert_record,
    SEND_STATUS_PENDING,
    SEND_STATUS_SENT,
    SEND_STATUS_FAILED,
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from common.feishu_api import run_cli

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _send_text(chat_id: str, text: str) -> bool:
    """通过 lark-cli 发送 markdown 消息到群"""
    try:
        r = run_cli("im", "+messages-send",
                     "--as", "bot",
                     "--chat-id", chat_id,
                     "--markdown", text)
        if r is None:
            logger.error("API 返回 None")
            return False
        if isinstance(r, dict) and r.get("ok"):
            return True
        if isinstance(r, dict):
            err_msg = r.get("error", {}).get("message", "unknown")
            logger.error(f"API 错误: {err_msg}")
            return False
        return bool(r)
    except Exception as e:
        logger.error(f"发送异常: {e}")
        return False


def fetch_pending() -> List[Dict]:
    """读取通知队列表中所有 待发送 记录"""
    fields = ("通知类型", "接收人", "消息内容", "发送状态")
    all_records = query_records(NOTIFY_TABLE_ID, *fields)
    return [r for r in all_records
            if r.get("发送状态") and _extract_text(r, "发送状态") == SEND_STATUS_PENDING]


def _extract_text(record: Dict, field_name: str) -> str:
    from shared.bitable_ops import _field_text
    return _field_text([record.get(field_name)], [field_name], field_name)


def _extract_user(record: Dict) -> tuple:
    """从人员字段提取 open_id 和 name"""
    val = record.get("接收人")
    if isinstance(val, list) and val:
        u = val[0]
        if isinstance(u, dict):
            return u.get("id", ""), u.get("name", "")
    return "", ""


def _extract_view_url(payload: Dict) -> str:
    """从 card 数据中提取第一个飞书表格链接"""
    card = payload.get("card", {})
    card_str = json.dumps(card, ensure_ascii=False)
    m = re.search(r'https://jcnj2ogjcmym\.feishu\.cn/base/\w+\?[^"]+', card_str)
    return m.group(0) if m else ""


def process_one(record: Dict) -> bool:
    """处理单条待发送通知"""
    rid = record.get("_record_id", "")
    ntype = _extract_text(record, "通知类型")
    content_raw = _extract_text(record, "消息内容")
    user_id, user_name = _extract_user(record)

    if not rid or not content_raw:
        logger.warning(f"记录不完整: {rid}")
        return False

    text = content_raw
    view_url = ""
    try:
        payload = json.loads(content_raw)
        text = payload.get("text", content_raw)
        view_url = _extract_view_url(payload)
    except (json.JSONDecodeError, TypeError):
        pass

    # 构建带 @mention 和链接的消息
    if user_id:
        name = user_name or "用户"
        text = f"<at user_id=\"{user_id}\">@{name}</at> {text}"
    if view_url:
        text = f"{text} 查看详情：{view_url}"

    ok = _send_text(NOTIFY_GROUP_CHAT_ID, text)

    now = _now_ts()
    status = SEND_STATUS_SENT if ok else SEND_STATUS_FAILED
    upsert_record(NOTIFY_TABLE_ID, rid, {
        "发送状态": status,
        "发送时间": now,
    })
    return ok


def flush_pending_notifications() -> None:
    """处理所有待发送通知（供 scan_cycle 调用）"""
    pending = fetch_pending()
    if not pending:
        return

    logger.info(f"[通知发送] {len(pending)} 条待处理")
    for record in pending:
        ntype = _extract_text(record, "通知类型")
        rid = record.get("_record_id", "")
        ok = process_one(record)
        status = "OK" if ok else "FAIL"
        logger.info(f"  [{status}] {ntype} ({rid})")


def main() -> None:
    logger.info("=" * 60)
    logger.info("通知发送 Worker")
    logger.info(f"群 chat_id: {NOTIFY_GROUP_CHAT_ID}")
    logger.info("=" * 60)
    flush_pending_notifications()


if __name__ == "__main__":
    main()
