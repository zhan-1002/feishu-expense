"""费用报销单 CRUD 封装"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .config import BASE_TOKEN, EXPENSE_TABLE_ID
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from common.feishu_api import run_cli

logger = logging.getLogger(__name__)

# ===========================================================================
# 字段名 → 字段 ID 映射
# ===========================================================================

EF: Dict[str, str] = {  # Expense Fields
    "报销摘要":     "fldfpYGEqn",
    "报销科目":     "fldPAZZQZ7",
    "相关单据":     "fldoMubX0u",
    "财务审批人员": "fldsBgOQh0",
    "报销人":       "fldN6522IU",
    "财务审批":     "fldShWqi4b",
    "报销金额":     "fldxMKs8Hy",
    "备注":         "fldPrV7tWI",
    "报销日期":     "fldt5b0Avt",
    "报销状态":     "flde8iD99Z",
}

# 状态常量
STATUS_DRAFT = "待提交"
STATUS_PENDING = "待审批"
STATUS_PASSED = "已通过"
STATUS_REJECTED = "已拒绝"

# 审批结论常量
APPROVAL_PENDING = "待审批"
APPROVAL_PASSED = "通过"
APPROVAL_REJECTED = "拒绝"

# ===========================================================================
# 字段提取辅助（简化版）
# ===========================================================================

def get_field_text(record: Dict[str, Any], field_name: str) -> str:
    """从记录中提取字段文本值

    Args:
        record: 记录字典
        field_name: 字段名

    Returns:
        字段文本值，无则返回空字符串
    """
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
    """从记录中提取用户字段的 open_id

    Args:
        record: 记录字典
        field_name: 字段名

    Returns:
        用户 open_id，无则返回空字符串
    """
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
    """检查字段是否有值

    Args:
        record: 记录字典
        field_name: 字段名

    Returns:
        字段是否有非空值
    """
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


# 兼容旧接口（已废弃，保留向后兼容）
def _field_text(row: List, field_names: List[str], key: str) -> str:
    """已废弃：请使用 get_field_text"""
    record = {name: val for name, val in zip(field_names, row)}
    return get_field_text(record, key)


def _field_user_id(row: List, field_names: List[str], key: str) -> str:
    """已废弃：请使用 get_field_user_id"""
    record = {name: val for name, val in zip(field_names, row)}
    return get_field_user_id(record, key)


# ===========================================================================
# 记录查询
# ===========================================================================

def query_records(table_id: str, *field_names: str) -> List[Dict[str, Any]]:
    """查询表中所有记录

    Args:
        table_id: 表格 ID
        *field_names: 字段名列表

    Returns:
        记录字典列表
    """
    if not field_names:
        return []

    args = ["base", "+record-list", "--base-token", BASE_TOKEN, "--table-id", table_id,
            "--limit", "200"]
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


def query_all_expenses() -> List[Dict[str, Any]]:
    """查询所有报销单

    Returns:
        报销单记录列表
    """
    field_names = [
        "报销摘要", "报销科目", "财务审批人员", "报销人",
        "财务审批", "报销金额", "备注", "报销日期", "报销状态",
    ]
    return query_records(EXPENSE_TABLE_ID, *field_names)


# ===========================================================================
# 记录更新
# ===========================================================================

def _make_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """将字段名映射转为 API 负载

    Args:
        fields: 字段字典

    Returns:
        API 负载字典
    """
    payload: Dict[str, Any] = {}
    user_fields = {"报销人", "财务审批人员"}
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


def upsert_record(table_id: str, record_id: str, fields: Dict[str, Any]) -> bool:
    """更新记录

    Args:
        table_id: 表格 ID
        record_id: 记录 ID
        fields: 要更新的字段字典

    Returns:
        是否成功
    """
    payload = _make_payload(fields)
    r = run_cli("base", "+record-upsert", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--record-id", record_id, "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"更新记录失败: {record_id}")
        return False
    return r.get("ok", False) if isinstance(r, dict) else False


def update_status(record_id: str, new_status: str) -> bool:
    """更新报销状态

    Args:
        record_id: 记录 ID
        new_status: 新状态值

    Returns:
        是否成功
    """
    return upsert_record(EXPENSE_TABLE_ID, record_id, {"报销状态": new_status})