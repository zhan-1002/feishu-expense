"""日历/节假日处理模块

处理大小周判断、节假日查询、工作日判断等
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Dict, List, Optional, Set

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
from common.feishu_api import run_cli

from .shared.config import CALENDAR_ID

logger = logging.getLogger(__name__)

# ===========================================================================
# 缓存
# ===========================================================================

# 节假日缓存: {date: True}  True表示是节假日
_holiday_cache: Dict[str, bool] = {}

# 调休日缓存: {date: True}  True表示是调休上班日
_adjustment_cache: Dict[str, bool] = {}

# 缓存过期时间
_cache_expire_date: Optional[date] = None


def _date_key(d: date) -> str:
    """日期转字符串key"""
    return d.strftime("%Y-%m-%d")


# ===========================================================================
# 大小周判断
# ===========================================================================

def get_week_of_month(saturday_date: date) -> int:
    """获取周六是该月第几周

    规则：以周六所在月份判断

    Args:
        saturday_date: 周六日期

    Returns:
        第几周（从1开始）
    """
    # 确保是周六
    if saturday_date.weekday() != 5:
        raise ValueError(f"传入日期不是周六: {saturday_date}")

    # 获取周六所在月份的第一天
    first_day = date(saturday_date.year, saturday_date.month, 1)

    # 找到该月第一个周六
    days_until_saturday = (5 - first_day.weekday()) % 7
    first_saturday = first_day + timedelta(days=days_until_saturday)

    # 如果第一个周六不在当月（跨月），则从第二个周六开始算
    if first_saturday.month != saturday_date.month:
        first_saturday += timedelta(days=7)

    # 计算当前周六是第几个周六
    weeks_diff = (saturday_date - first_saturday).days // 7
    return weeks_diff + 1


def is_big_week(saturday_date: date) -> bool:
    """判断是否为大周（上班）

    大周：该月第二周的周六
    小周：其他周六

    Args:
        saturday_date: 周六日期

    Returns:
        是否为大周
    """
    week_num = get_week_of_month(saturday_date)
    return week_num == 2


def get_week_saturday(week_start: date) -> date:
    """获取本周周六日期

    Args:
        week_start: 周一日期

    Returns:
        周六日期
    """
    # 周一(0) → 周六(5) 相差5天
    return week_start + timedelta(days=5)


def get_week_month(week_start: date) -> str:
    """获取周所属月份

    规则：以周六所在月份判断

    Args:
        week_start: 周一日期

    Returns:
        月份字符串，格式 YYYY-MM
    """
    saturday = get_week_saturday(week_start)
    return saturday.strftime("%Y-%m")


# ===========================================================================
# 节假日查询
# ===========================================================================

def fetch_holidays(year: int, month: int) -> Set[str]:
    """从飞书日历获取节假日

    Args:
        year: 年份
        month: 月份

    Returns:
        节假日日期集合（格式 YYYY-MM-DD）
    """
    if not CALENDAR_ID:
        logger.warning("CALENDAR_ID 未配置，无法获取节假日")
        return set()

    # 构建日期范围
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    args = [
        "calendar", "event-list",
        "--calendar-id", CALENDAR_ID,
        "--start-time", start_date.strftime("%Y-%m-%d"),
        "--end-time", end_date.strftime("%Y-%m-%d"),
    ]

    result = run_cli(*args, timeout=30)
    if result is None:
        logger.warning(f"获取节假日失败: {year}-{month:02d}")
        return set()

    holidays: Set[str] = set()
    events = result.get("events", []) if isinstance(result, dict) else []

    for event in events:
        # 假设节假日事件包含特定标识
        event_type = event.get("type", "")
        if "holiday" in event_type.lower() or event.get("is_holiday"):
            start = event.get("start_time", "")
            if start:
                holidays.add(start[:10])

    return holidays


def fetch_adjustments(year: int, month: int) -> Set[str]:
    """从飞书日历获取调休上班日

    Args:
        year: 年份
        month: 月份

    Returns:
        调休上班日集合（格式 YYYY-MM-DD）
    """
    if not CALENDAR_ID:
        return set()

    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year, month + 1, 1) - timedelta(days=1)

    args = [
        "calendar", "event-list",
        "--calendar-id", CALENDAR_ID,
        "--start-time", start_date.strftime("%Y-%m-%d"),
        "--end-time", end_date.strftime("%Y-%m-%d"),
    ]

    result = run_cli(*args, timeout=30)
    if result is None:
        return set()

    adjustments: Set[str] = set()
    events = result.get("events", []) if isinstance(result, dict) else []

    for event in events:
        # 调休上班日包含特定标识
        if event.get("is_workday") or "调休" in event.get("summary", ""):
            start = event.get("start_time", "")
            if start:
                adjustments.add(start[:10])

    return adjustments


def refresh_cache(year: int, month: int) -> None:
    """刷新缓存

    Args:
        year: 年份
        month: 月份
    """
    global _holiday_cache, _adjustment_cache, _cache_expire_date

    logger.info(f"[日历] 刷新缓存: {year}-{month:02d}")

    holidays = fetch_holidays(year, month)
    adjustments = fetch_adjustments(year, month)

    # 更新缓存
    for h in holidays:
        _holiday_cache[h] = True
    for a in adjustments:
        _adjustment_cache[a] = True

    # 设置缓存过期时间（下个月1日）
    if month == 12:
        _cache_expire_date = date(year + 1, 1, 1)
    else:
        _cache_expire_date = date(year, month + 1, 1)


def is_holiday(d: date) -> bool:
    """判断是否为节假日

    Args:
        d: 日期

    Returns:
        是否为节假日
    """
    # 检查缓存是否过期
    if _cache_expire_date and d >= _cache_expire_date:
        refresh_cache(d.year, d.month)

    key = _date_key(d)
    return _holiday_cache.get(key, False)


def is_adjustment_workday(d: date) -> bool:
    """判断是否为调休上班日

    Args:
        d: 日期

    Returns:
        是否为调休上班日
    """
    if _cache_expire_date and d >= _cache_expire_date:
        refresh_cache(d.year, d.month)

    key = _date_key(d)
    return _adjustment_cache.get(key, False)


# ===========================================================================
# 工作日判断
# ===========================================================================

def is_workday(d: date, check_big_week: bool = True) -> bool:
    """判断是否为工作日

    逻辑：
    1. 周一至周五：默认工作日，除非是节假日
    2. 周六：大周上班，小周不上班
    3. 周日：默认不上班，除非调休

    Args:
        d: 日期
        check_big_week: 是否检查大小周（周六）

    Returns:
        是否为工作日
    """
    weekday = d.weekday()
    key = _date_key(d)

    # 先检查是否为节假日
    if is_holiday(d):
        return False

    # 周一至周五（0-4）
    if weekday < 5:
        return True

    # 周六（5）
    if weekday == 5:
        if check_big_week:
            return is_big_week(d)
        return False

    # 周日（6）：检查调休
    return is_adjustment_workday(d)


def get_month_workdays(year: int, month: int) -> int:
    """获取指定月份的工作日数量

    Args:
        year: 年份
        month: 月份

    Returns:
        工作日数量
    """
    first_day = date(year, month, 1)
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    count = 0
    current = first_day
    while current <= last_day:
        if is_workday(current):
            count += 1
        current += timedelta(days=1)

    return count


def get_week_workdays(week_start: date) -> int:
    """获取指定周的工作日数量

    Args:
        week_start: 周一日期

    Returns:
        工作日数量
    """
    count = 0
    for i in range(7):
        d = week_start + timedelta(days=i)
        if is_workday(d):
            count += 1
    return count
