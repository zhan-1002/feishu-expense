"""
两表 CRUD 封装（明细表已合并入任务表）

所有 Bitable 读写通过 run_cli() 完成，提供类型化的字段映射。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .config import (
    BUSINESS_TABLE_ID,
    TASK_TABLE_ID,
    NOTIFY_TABLE_ID,
    BASE_TOKEN,
)
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))

from common.feishu_api import run_cli

logger = logging.getLogger(__name__)

# ===========================================================================
# 字段名 → 字段 ID 映射
# ===========================================================================

BF: Dict[str, str] = {  # Business Fields
    "_id":          "fldpyZyYfU",
    "商品标题":       "fldXR6m66b",
    "商品链接":       "fldkf97I84",
    "商品图片":       "fldzfZesWB",
    "任务说明":       "fldKc1bzlK",
    "供应链专员":     "fldpVE7xX4",
    "供应商链接":     "fldGn7OXCT",
    "初步报价":       "fld3jVczmJ",
    "初步总成本":     "fldwboXLab",
    "预估售价":       "fldZRVaJlA",
    "初步调研备注":   "fldt50FpCM",
    "消费者关注点":   "fldtiwdwDc",
    "差异化方案":     "fldLPrgQ95",
    "初审结论":       "fldjXmxrQa",
    "初审意见":       "fldmu42OHy",
    "终审结论":       "fld2d2SUd7",
    "终审意见":       "fldKYRwIk5",
    "当前阶段":       "fldxizzz3p",
    "最后更新时间":   "fldV4DDinw",
    "补充完成":       "fld2XUNAp0",
    "截止时间":       "fld6p3fPtQ",
}

TF: Dict[str, str] = {  # Task Fields
    "_id":         "fldDKdqzz8",
    "任务名称":     "fldYrJswzJ",
    "任务类型":     "fldcKRhl2O",
    "任务执行人":   "fldl9nNxAX",
    "优先级":       "fldpoQAB8Z",
    "进展":         "fldEp9g1mg",
    "开始日期":     "flddkx0wgT",
    "实际完成":     "fldA1Mkx6J",
    "关联商品":     "fldDZ10vjT",
    "处理结论":     "fldLzIHU5r",
}

NF: Dict[str, str] = {  # Notify Fields
    "_id":         "fld_PLACEHOLDER_NID",
    "通知类型":     "fldIwRphcp",
    "接收人":       "fldn5fjvFa",
    "消息内容":     "fld01QgR5G",
    "发送状态":     "fldNiT0zND",
    "创建时间":     "fldsEBG6XM",
    "发送时间":     "fldF063Q6C",
}

# 反向映射
BF_ID_TO_NAME: Dict[str, str] = {v: k for k, v in BF.items()}
TF_ID_TO_NAME: Dict[str, str] = {v: k for k, v in TF.items()}
NF_ID_TO_NAME: Dict[str, str] = {v: k for k, v in NF.items()}

# ===========================================================================
# 阶段常量
# ===========================================================================

STAGE_DISPATCH = "待派发"
STAGE_FIRST_RESEARCH = "待初步调研"
STAGE_FIRST_REVIEW = "待初审"
STAGE_SECOND_OPTIMIZE = "待二次优化"
STAGE_FINAL_REVIEW = "待终审"
STAGE_SUPPLEMENT = "待补充"
STAGE_PURCHASE = "进入采购"
STAGE_ENDED = "已结束"

ACTIVE_STAGES: List[str] = [
    STAGE_DISPATCH,
    STAGE_FIRST_RESEARCH,
    STAGE_FIRST_REVIEW,
    STAGE_SECOND_OPTIMIZE,
    STAGE_FINAL_REVIEW,
    STAGE_SUPPLEMENT,
]

# 通知类型常量
NOTIFY_TYPE_DISPATCH = "任务派发"
NOTIFY_TYPE_REVIEW = "审核通知"
NOTIFY_TYPE_RESULT = "结果通知"
NOTIFY_TYPE_REMINDER = "催办通知"

# 处理结论常量
CONCLUSION_PENDING = "待处理"
CONCLUSION_PASSED = "已通过"
CONCLUSION_REJECTED = "已终止"
CONCLUSION_RETURNED = "已退回"

TERMINAL_CONCLUSIONS: Tuple[str, ...] = (CONCLUSION_PASSED, CONCLUSION_REJECTED)

# 发送状态常量
SEND_STATUS_PENDING = "待发送"
SEND_STATUS_SENT = "已发送"
SEND_STATUS_FAILED = "发送失败"

# ===========================================================================
# 字段提取辅助
# ===========================================================================


def _field_val(row: List, field_names: List[str], key: str) -> Any:
    for i, name in enumerate(field_names):
        if name == key and i < len(row):
            return row[i]
    return None


def _field_text(row: List, field_names: List[str], key: str) -> str:
    val = _field_val(row, field_names, key)
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list) and val:
        if isinstance(val[0], dict):
            return val[0].get("text", "") or val[0].get("name", "") or val[0].get("id", "")
        return str(val[0])
    if isinstance(val, dict):
        return val.get("text", "") or val.get("name", "") or val.get("id", "") or str(val)
    return str(val)


def _field_user_id(row: List, field_names: List[str], key: str) -> str:
    val = _field_val(row, field_names, key)
    if isinstance(val, list) and val:
        if isinstance(val[0], dict):
            return val[0].get("id", "")
        return str(val[0])
    if isinstance(val, dict):
        return val.get("id", "")
    if isinstance(val, str):
        return val
    return ""


def _field_link_record_id(row: List, field_names: List[str], key: str) -> str:
    val = _field_val(row, field_names, key)
    if isinstance(val, list) and val:
        if isinstance(val[0], dict):
            return val[0].get("record_id", "") or val[0].get("id", "") or ""
        if isinstance(val[0], str):
            return val[0]
    if isinstance(val, dict):
        return val.get("record_id", "") or val.get("id", "") or ""
    if isinstance(val, str):
        return val
    return ""


# ===========================================================================
# 记录查询
# ===========================================================================


def query_records(table_id: str, *field_names: str) -> List[Dict[str, Any]]:
    """查询表中所有记录，field_names 为字段名"""
    if not field_names:
        return []

    args = ["base", "+record-list", "--base-token", BASE_TOKEN, "--table-id", table_id,
            "--limit", "200", "--format", "json"]
    for fn in field_names:
        args.extend(["--field-id", fn])

    result = run_cli(*args)
    if result is None:
        logger.error(f"查询记录失败: table={table_id}")
        return []
    
    if not isinstance(result, dict) or not result.get("ok"):
        logger.error(f"查询记录返回异常: {result}")
        return []

    data = result.get("data", {})
    rows = data.get("data", [])
    fields = data.get("fields", [])
    ids = data.get("record_id_list", [])

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
# 记录写入
# ===========================================================================


def _make_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """将字段名映射转为 API 负载，处理用户字段特殊格式"""
    payload: Dict[str, Any] = {}
    user_fields = {"供应链专员", "任务执行人", "接收人"}
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
    payload = _make_payload(fields)
    r = run_cli("base", "+record-upsert", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--record-id", record_id, "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"更新记录失败: {record_id}")
        return False
    return r.get("ok", False) if isinstance(r, dict) else False


def batch_upsert_records(table_id: str, records: List[Dict]) -> bool:
    """批量更新记录（注意：当前为逐条调用，效率较低）"""
    if not records:
        return True
    ok = True
    for rec in records:
        rid = rec.pop("_record_id", None)
        if not rid:
            continue
        if not upsert_record(table_id, rid, rec):
            ok = False
    return ok


def _create_record(table_id: str, fields: Dict[str, Any]) -> str:
    """创建单条记录，返回 record_id"""
    payload = _make_payload(fields)
    r = run_cli("base", "+record-upsert", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--json", json.dumps(payload, ensure_ascii=False))
    if not r or not isinstance(r, dict) or not r.get("ok"):
        logger.error(f"创建记录失败: {fields.get('任务名称', 'unknown')}")
        return ""
    ids = r.get("data", {}).get("record", {}).get("record_id_list", [])
    return ids[0] if ids else ""


# ===========================================================================
# 业务表操作
# ===========================================================================


def query_all_business() -> List[Dict[str, Any]]:
    field_names = [
        "商品标题", "商品链接", "供应链专员", "供应商链接",
        "初步报价", "初步总成本", "预估售价",
        "消费者关注点", "差异化方案",
        "初审结论", "终审结论", "当前阶段", "最后更新时间", "补充完成",
        "截止时间",
    ]
    return query_records(BUSINESS_TABLE_ID, *field_names)


def advance_stage(record_id: str, new_stage: str, extra_fields: Optional[Dict[str, Any]] = None) -> bool:
    fields: Dict[str, Any] = {
        "当前阶段": new_stage,
        "最后更新时间": int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    if extra_fields:
        fields.update(extra_fields)
    return upsert_record(BUSINESS_TABLE_ID, record_id, fields)


def batch_advance_stage(record_ids: List[str], new_stage: str) -> bool:
    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    records = [
        {"_record_id": rid, "当前阶段": new_stage, "最后更新时间": now_ts}
        for rid in record_ids
    ]
    return batch_upsert_records(BUSINESS_TABLE_ID, records)


# ===========================================================================
# 任务表操作
# ===========================================================================


def create_task(
    name: str,
    task_type: str,
    assignee_id: str,
    business_id: str,
    priority: str = "重要",
) -> Optional[str]:
    """创建任务（1:1），返回 task record_id"""
    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    rid = _create_record(TASK_TABLE_ID, {
        "任务名称": name,
        "任务类型": task_type,
        "任务执行人": assignee_id,
        "关联商品": business_id,
        "处理结论": CONCLUSION_PENDING,
        "优先级": priority,
        "进展": "创建",
        "开始日期": now_ts,
    })
    return rid if rid else None


def update_task_conclusion(task_id: str, conclusion: str) -> bool:
    """更新任务处理结论"""
    return upsert_record(TASK_TABLE_ID, task_id, {"处理结论": conclusion})


def update_task_progress(task_id: str, progress: str) -> bool:
    fields: Dict[str, Any] = {"进展": progress}
    if progress == "已完成":
        fields["实际完成"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    return upsert_record(TASK_TABLE_ID, task_id, fields)


def query_all_tasks() -> List[Dict[str, Any]]:
    return query_records(
        TASK_TABLE_ID,
        "任务名称", "任务类型", "任务执行人", "进展",
        "关联商品", "处理结论", "开始日期",
    )


def query_task_by_business(business_id: str) -> Optional[Dict[str, Any]]:
    """根据关联商品查找任务"""
    tasks = query_all_tasks()
    for t in tasks:
        linked = _field_link_record_id(
            [t.get("关联商品")], ["关联商品"], "关联商品")
        if linked == business_id:
            return t
    return None


# ===========================================================================
# 通知队列表操作
# ===========================================================================


def enqueue_notification(
    notify_type: str,
    receiver_id: str,
    content: str,
) -> str:
    """写入通知队列，返回 record_id"""
    now_ts = int(datetime.now(timezone.utc).timestamp() * 1000)
    return _create_record(NOTIFY_TABLE_ID, {
        "通知类型": notify_type,
        "接收人": receiver_id,
        "消息内容": content,
        "发送状态": SEND_STATUS_PENDING,
        "创建时间": now_ts,
    })
