"""实习工时模块 CRUD 封装"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import BASE_TOKEN, WEEKLY_ATTENDANCE_TABLE_ID, MONTHLY_SUMMARY_TABLE_ID
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from common.feishu_api import run_cli

logger = logging.getLogger(__name__)

# ===========================================================================
# 字段提取辅助
# ===========================================================================

def get_field_text(record: Dict[str, Any], field_name: str) -> str:
    """从记录中提取字段文本值"""
    val = record.get(field_name)
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list) and val:
        item = val[0]
        if isinstance(item, dict):
            return item.get("text", "") or item.get("name", "") or item.get("id", "")
        return str(item)
    if isinstance(val, dict):
        return val.get("text", "") or val.get("name", "") or val.get("id", "") or ""
    return str(val)


def get_field_user_id(record: Dict[str, Any], field_name: str) -> str:
    """从记录中提取用户字段的 open_id"""
    val = record.get(field_name)
    if isinstance(val, list) and val:
        item = val[0]
        if isinstance(item, dict):
            return item.get("id", "")
        return str(item)
    if isinstance(val, dict):
        return val.get("id", "")
    if isinstance(val, str):
        return val
    return ""


def has_field_value(record: Dict[str, Any], field_name: str) -> bool:
    """检查字段是否有值"""
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
# 记录查询
# ===========================================================================

def query_records(table_id: str, *field_names: str) -> List[Dict[str, Any]]:
    """查询表中所有记录"""
    if not field_names:
        return []

    args = ["base", "+record-list", "--base-token", BASE_TOKEN, "--table-id", table_id,
            "--limit", "500"]
    for fn in field_names:
        args.extend(["--field-id", fn])

    result = run_cli(*args)
    if result is None:
        logger.error(f"查询记录失败: table={table_id}")
        return []

    if not isinstance(result, dict) or not result.get("ok"):
        logger.error(f"查询记录返回异常: {result}")
        return []

    data = result.get("data") or {}
    rows = data.get("data") or []
    fields = data.get("fields") or []
    ids = data.get("record_id_list") or []

    records: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        rec: Dict[str, Any] = {}
        rec["_record_id"] = ids[i] if i < len(ids) else ""
        for j, fn in enumerate(fields):
            if j < len(row):
                rec[fn] = row[j]
        records.append(rec)

    return records


# ===========================================================================
# 记录更新
# ===========================================================================

def upsert_record(table_id: str, record_id: str, fields: Dict[str, Any]) -> bool:
    """更新记录"""
    payload = _make_payload(fields)
    r = run_cli("base", "+record-upsert", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--record-id", record_id, "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"更新记录失败: {record_id}")
        return False
    return r.get("ok", False) if isinstance(r, dict) else False


def create_record(table_id: str, fields: Dict[str, Any]) -> Optional[str]:
    """创建新记录"""
    payload = _make_payload(fields)
    r = run_cli("base", "+record-create", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"创建记录失败: table={table_id}")
        return None
    if isinstance(r, dict) and r.get("ok"):
        return r.get("record_id")
    return None


def _make_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """将字段字典转为 API 负载"""
    user_fields = {"员工"}
    payload: Dict[str, Any] = {}
    for fname, value in fields.items():
        if fname in user_fields:
            if isinstance(value, str) and value:
                payload[fname] = [{"id": value}]
            elif isinstance(value, list):
                payload[fname] = value
            else:
                payload[fname] = value
        else:
            payload[fname] = value
    return payload
