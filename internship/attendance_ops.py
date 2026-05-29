"""出勤记录操作模块

周出勤记录的CRUD操作
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Set

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from common.feishu_api import run_cli
from .shared.bitable_ops import get_field_text, get_field_user_id

from .shared.config import (
    BASE_TOKEN,
    WEEKLY_ATTENDANCE_TABLE_ID,
    STATUS_DRAFT, STATUS_PENDING, STATUS_CONFIRMED,
    ATTENDANCE_FULL, ATTENDANCE_AM, ATTENDANCE_PM, ATTENDANCE_NONE,
)
from .calendar import get_week_month, is_workday

logger = logging.getLogger(__name__)

# ===========================================================================
# 字段名常量
# ===========================================================================

FIELD_EMPLOYEE = "员工"
FIELD_WEEK_START = "周开始日期"
FIELD_WEEK_END = "周结束日期"
FIELD_MONDAY = "周一"
FIELD_TUESDAY = "周二"
FIELD_WEDNESDAY = "周三"
FIELD_THURSDAY = "周四"
FIELD_FRIDAY = "周五"
FIELD_SATURDAY = "周六"
FIELD_SUNDAY = "周日"
FIELD_STATUS = "出勤状态"
FIELD_FILL_TIME = "填写时间"
FIELD_CONFIRM_TIME = "确认时间"
FIELD_MONTH = "所属月份"

DAY_FIELDS = [FIELD_MONDAY, FIELD_TUESDAY, FIELD_WEDNESDAY, FIELD_THURSDAY,
              FIELD_FRIDAY, FIELD_SATURDAY, FIELD_SUNDAY]


# ===========================================================================
# 记录查询
# ===========================================================================

def query_records(table_id: str, field_names: List[str]) -> List[Dict[str, Any]]:
    """查询表中所有记录

    Args:
        table_id: 表格 ID
        field_names: 字段名列表

    Returns:
        记录字典列表
    """
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


def query_all_weekly_records() -> List[Dict[str, Any]]:
    """查询所有周出勤记录

    Returns:
        周出勤记录列表
    """
    field_names = [
        FIELD_EMPLOYEE, FIELD_WEEK_START, FIELD_WEEK_END,
        FIELD_MONDAY, FIELD_TUESDAY, FIELD_WEDNESDAY,
        FIELD_THURSDAY, FIELD_FRIDAY, FIELD_SATURDAY, FIELD_SUNDAY,
        FIELD_STATUS, FIELD_FILL_TIME, FIELD_CONFIRM_TIME, FIELD_MONTH,
    ]
    return query_records(WEEKLY_ATTENDANCE_TABLE_ID, field_names)


def get_week_record(employee_id: str, week_start: date) -> Optional[Dict[str, Any]]:
    """获取指定员工的指定周记录

    Args:
        employee_id: 员工 open_id
        week_start: 周一开始日期

    Returns:
        记录字典，无则返回 None
    """
    records = query_all_weekly_records()
    week_start_str = week_start.strftime("%Y-%m-%d")

    for rec in records:
        emp = get_field_user_id(rec, FIELD_EMPLOYEE)
        ws = get_field_text(rec, FIELD_WEEK_START)
        # 处理日期格式
        ws = ws[:10] if ws else ""

        if emp == employee_id and ws == week_start_str:
            return rec

    return None


def get_employee_ids_from_records(records: List[Dict[str, Any]]) -> Set[str]:
    """从记录中提取所有员工ID

    Args:
        records: 记录列表

    Returns:
        员工ID集合
    """
    ids: Set[str] = set()
    for rec in records:
        emp_id = get_field_user_id(rec, FIELD_EMPLOYEE)
        if emp_id:
            ids.add(emp_id)
    return ids


def get_records_by_status(records: List[Dict[str, Any]], status: str) -> List[Dict[str, Any]]:
    """按状态筛选记录

    Args:
        records: 记录列表
        status: 状态值

    Returns:
        筛选后的记录列表
    """
    return [r for r in records if get_field_text(r, FIELD_STATUS) == status]


def get_records_by_month(records: List[Dict[str, Any]], month: str) -> List[Dict[str, Any]]:
    """按月份筛选记录

    Args:
        records: 记录列表
        month: 月份字符串 YYYY-MM

    Returns:
        筛选后的记录列表
    """
    return [r for r in records if get_field_text(r, FIELD_MONTH) == month]


# ===========================================================================
# 记录创建
# ===========================================================================

def create_record(table_id: str, fields: Dict[str, Any]) -> Optional[str]:
    """创建新记录

    Args:
        table_id: 表格 ID
        fields: 字段字典

    Returns:
        记录 ID，失败返回 None
    """
    payload = _make_payload(fields)
    r = run_cli("base", "+record-create", "--base-token", BASE_TOKEN, "--table-id", table_id,
                 "--json", json.dumps(payload, ensure_ascii=False))
    if r is None:
        logger.error(f"创建记录失败: table={table_id}")
        return None

    if isinstance(r, dict) and r.get("ok"):
        return r.get("record_id")
    return None


def create_weekly_record(employee_id: str, week_start: date) -> Optional[str]:
    """创建周出勤记录

    Args:
        employee_id: 员工 open_id
        week_start: 周一开始日期

    Returns:
        记录 ID，失败返回 None
    """
    week_end = week_start + timedelta(days=6)
    month = get_week_month(week_start)

    fields = {
        FIELD_EMPLOYEE: employee_id,
        FIELD_WEEK_START: week_start.strftime("%Y-%m-%d"),
        FIELD_WEEK_END: week_end.strftime("%Y-%m-%d"),
        FIELD_STATUS: STATUS_DRAFT,
        FIELD_MONTH: month,
    }

    # 初始化各天的出勤状态为空
    for day_field in DAY_FIELDS:
        fields[day_field] = ""

    record_id = create_record(WEEKLY_ATTENDANCE_TABLE_ID, fields)
    if record_id:
        logger.info(f"[创建] 周记录: employee={employee_id}, week={week_start}, month={month}")
    return record_id


def batch_create_weekly_records(employee_ids: List[str], week_start: date) -> int:
    """批量创建周出勤记录

    Args:
        employee_ids: 员工 open_id 列表
        week_start: 周一开始日期

    Returns:
        成功创建数量
    """
    count = 0
    for emp_id in employee_ids:
        # 检查是否已存在
        existing = get_week_record(emp_id, week_start)
        if existing:
            logger.info(f"[跳过] 周记录已存在: employee={emp_id}, week={week_start}")
            continue

        record_id = create_weekly_record(emp_id, week_start)
        if record_id:
            count += 1

    logger.info(f"[批量创建] 完成: {count}/{len(employee_ids)}")
    return count


# ===========================================================================
# 记录更新
# ===========================================================================

def _make_payload(fields: Dict[str, Any]) -> Dict[str, Any]:
    """将字段字典转为 API 负载

    Args:
        fields: 字段字典

    Returns:
        API 负载字典
    """
    payload: Dict[str, Any] = {}
    for fname, value in fields.items():
        # 人员字段特殊处理
        if fname == FIELD_EMPLOYEE:
            if isinstance(value, str) and value:
                payload[fname] = [{"id": value}]
            elif isinstance(value, list):
                payload[fname] = value
        # 日期字段特殊处理
        elif fname in [FIELD_WEEK_START, FIELD_WEEK_END, FIELD_FILL_TIME, FIELD_CONFIRM_TIME]:
            if isinstance(value, (date, datetime)):
                payload[fname] = value.strftime("%Y-%m-%d")
            else:
                payload[fname] = value
        else:
            payload[fname] = value
    return payload


def update_record(table_id: str, record_id: str, fields: Dict[str, Any]) -> bool:
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
        logger.error(f"更新记录失败: record_id={record_id}")
        return False
    return r.get("ok", False) if isinstance(r, dict) else False


def update_status(record_id: str, new_status: str, time_field: str = None) -> bool:
    """更新出勤状态

    Args:
        record_id: 记录 ID
        new_status: 新状态
        time_field: 时间字段名（可选）

    Returns:
        是否成功
    """
    fields = {FIELD_STATUS: new_status}
    if time_field:
        fields[time_field] = datetime.now()
    return update_record(WEEKLY_ATTENDANCE_TABLE_ID, record_id, fields)


def confirm_record(record_id: str) -> bool:
    """确认周出勤记录

    Args:
        record_id: 记录 ID

    Returns:
        是否成功
    """
    return update_status(record_id, STATUS_CONFIRMED, FIELD_CONFIRM_TIME)


def mark_pending(record_id: str) -> bool:
    """标记为待确认状态（员工填写后）

    Args:
        record_id: 记录 ID

    Returns:
        是否成功
    """
    return update_status(record_id, STATUS_PENDING, FIELD_FILL_TIME)


# ===========================================================================
# 出勤计算
# ===========================================================================

def calculate_attendance_days(record: Dict[str, Any], target_month: str = None) -> float:
    """计算出勤天数

    Args:
        record: 周出勤记录
        target_month: 目标月份 YYYY-MM（可选，用于跨月计算）

    Returns:
        出勤天数（半天=0.5）
    """
    total = 0.0
    week_start_str = get_field_text(record, FIELD_WEEK_START)
    if not week_start_str:
        return 0.0

    try:
        week_start = datetime.strptime(week_start_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return 0.0

    for i, day_field in enumerate(DAY_FIELDS):
        current_date = week_start + timedelta(days=i)

        # 如果指定了目标月份，只计算该月份的天数
        if target_month:
            current_month = current_date.strftime("%Y-%m")
            if current_month != target_month:
                continue

        # 检查是否为工作日
        if not is_workday(current_date):
            continue

        status = get_field_text(record, day_field)

        if status == ATTENDANCE_FULL:
            total += 1.0
        elif status in (ATTENDANCE_AM, ATTENDANCE_PM):
            total += 0.5

    return total


def calculate_month_attendance(records: List[Dict[str, Any]], month: str) -> Dict[str, float]:
    """计算指定月份各员工的出勤天数

    Args:
        records: 周出勤记录列表
        month: 月份 YYYY-MM

    Returns:
        {员工ID: 出勤天数} 字典
    """
    result: Dict[str, float] = {}

    for rec in records:
        emp_id = get_field_user_id(rec, FIELD_EMPLOYEE)
        if not emp_id:
            continue

        days = calculate_attendance_days(rec, month)
        if emp_id in result:
            result[emp_id] += days
        else:
            result[emp_id] = days

    return result