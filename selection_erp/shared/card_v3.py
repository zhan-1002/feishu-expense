"""
V3 纯通知卡片构建器

原则：
- 所有卡片仅一个跳转按钮，无 callback
- 复用 V2 的工具函数和组件（_clean, _validate_url, _stat_panel 等）
- 同尺寸同布局，统计面板 + 跳转链接
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

Card = Dict[str, Any]


class CardBuildError(ValueError):
    """卡片构建参数错误"""


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_MAX_SUMMARY = 120


# ---------------------------------------------------------------------------
# 工具函数（从 card_v2.py 提取复用）
# ---------------------------------------------------------------------------

def _clean(name: str, value: Any, *, allow_empty: bool = False) -> str:
    if value is None:
        if allow_empty:
            return ""
        raise CardBuildError(f"{name} cannot be None")
    text = _CONTROL_RE.sub("", str(value)).strip()
    if not text and not allow_empty:
        raise CardBuildError(f"{name} cannot be empty")
    return text


def _truncate(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", _clean("text", text, allow_empty=True))
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _plain(content: Any) -> Card:
    return {"tag": "plain_text", "content": _clean("plain_text.content", content)}


def _md(content: Any, *, text_size: str = "normal") -> Card:
    return {"tag": "markdown", "content": _clean("markdown.content", content), "text_size": text_size}


def _hr() -> Card:
    return {"tag": "hr"}


def _validate_url(name: str, url: str) -> str:
    from urllib.parse import urlsplit
    url = _clean(name, url)
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https", "lark"}:
        raise CardBuildError(f"{name} must use http, https, or lark scheme")
    if parsed.scheme in {"http", "https"} and not parsed.netloc:
        raise CardBuildError(f"{name} must be an absolute URL")
    return url


# ---------------------------------------------------------------------------
# 组件
# ---------------------------------------------------------------------------

def _at_user(user_id: str) -> str:
    """返回 <at> 标签，markdown 中渲染用户头像+姓名"""
    return f"<at id={user_id}></at>"


def _url_button(label: str, url: str, *, button_type: str = "primary") -> Card:
    return {
        "tag": "button",
        "text": _plain(label),
        "type": button_type,
        "width": "fill",
        "size": "medium",
        "behaviors": [{"type": "open_url", "default_url": _validate_url("button url", url)}],
    }


def _stat_panel(columns_data: Sequence[tuple]) -> Card:
    """统计面板：每项 (label, value)，灰色背景列
    """
    if not columns_data:
        raise CardBuildError("stats cannot be empty")
    columns = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "vertical_align": "top",
            "background_style": "grey",
            "padding": "10px",
            "elements": [
                _md(f"**{_clean('stat.label', label)}**", text_size="notation"),
                _md(_clean("stat.value", str(value), allow_empty=True) or "-", text_size="normal"),
            ],
        }
        for label, value in columns_data
    ]
    flex = {1: "bisect", 2: "bisect", 3: "trisect"}.get(len(columns), "flow")
    return {
        "tag": "column_set",
        "flex_mode": flex,
        "horizontal_spacing": "8px",
        "columns": columns,
    }


# ---------------------------------------------------------------------------
# 基础卡片框架
# ---------------------------------------------------------------------------

def _base_card(
    *,
    title: str,
    subtitle: str,
    template: str,
    tag_text: str,
    tag_color: str,
    elements: List[Card],
    summary: str,
) -> Card:
    return {
        "schema": "2.0",
        "config": {
            "width_mode": "compact",
            "update_multi": True,
            "enable_forward": True,
            "summary": {"content": _truncate(summary, _MAX_SUMMARY)},
        },
        "header": {
            "title": _plain(title),
            "subtitle": _plain(subtitle),
            "template": template,
            "text_tag_list": [
                {"tag": "text_tag", "text": _plain(tag_text), "color": tag_color}
            ],
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "vertical_spacing": "12px",
            "elements": elements,
        },
    }


# ---------------------------------------------------------------------------
# 1. 任务派发通知卡（发给业务员）
# ---------------------------------------------------------------------------

def build_task_dispatch_card(
    *,
    task_type: str,
    count: int,
    assignee_name: str = "",
    assignee_id: str = "",
    view_url: str = "",
) -> Card:
    """通知业务员有新的派发任务"""
    view_url = _validate_url("view_url", view_url)
    type_label = "初审" if task_type == "first" else "终审"
    assignee_name = _clean("assignee_name", assignee_name, allow_empty=True) or "业务员"

    greeting = f"{_at_user(assignee_id)}，你有 **{count} 条**商品需要进行**{type_label}**调研。" if assignee_id else f"{assignee_name}，你有 **{count} 条**商品需要进行**{type_label}**调研。"

    elements: List[Card] = [
        _md(greeting),
        _md("请在业务表中填写供应商链接、报价、成本等字段后，系统将自动提交审核。"),
        _hr(),
        _url_button("\U0001f4ca 打开我的任务", view_url),
        _hr(),
        _md("填写完成后无需额外操作，系统每 5 分钟自动扫描并推进阶段。", text_size="notation"),
    ]

    return _base_card(
        title="\U0001f4e6 新的选品任务",
        subtitle=f"{type_label}调研 · {count} 条",
        template="blue",
        tag_text="待处理",
        tag_color="blue",
        elements=elements,
        summary=f"新的选品任务 ｜ {type_label}调研 {count} 条",
    )


# ---------------------------------------------------------------------------
# 2. 审核通知卡（发给主管）
# ---------------------------------------------------------------------------

def build_review_notification_card(
    *,
    first_review_count: int = 0,
    first_returned: int = 0,
    final_review_count: int = 0,
    final_returned: int = 0,
    first_view_url: str = "",
    final_view_url: str = "",
    reviewer_ids: Optional[List[str]] = None,
) -> Card:
    """通知主管有待审核任务，合并初审和终审"""
    first_view_url = _validate_url("first_view_url", first_view_url)
    final_view_url = _validate_url("final_view_url", final_view_url) if final_view_url else first_view_url

    stats = []
    total_returned = first_returned + final_returned

    if first_review_count > 0:
        stats.append(("待初审", f"{first_review_count} 条"))

    if total_returned > 0:
        stats.append(("退回重审", f"{total_returned} 条"))

    if final_review_count > 0:
        stats.append(("待终审", f"{final_review_count} 条"))

    total = first_review_count + total_returned + final_review_count
    description = "请审核以下任务：" if stats else "当前没有待审核任务。"

    elements: List[Card] = []

    if reviewer_ids:
        at_tags = " ".join(_at_user(rid) for rid in reviewer_ids)
        elements.append(_md(f"**审核人**：{at_tags}"))
        elements.append(_hr())

    elements.append(_md(description))

    if stats:
        elements.append(_stat_panel(stats))

    elements.append(_hr())

    # 两张卡分别有初审/终审两个跳转时，用两个按钮
    if first_review_count > 0 and final_review_count > 0:
        elements.append({
            "tag": "column_set",
            "flex_mode": "bisect",
            "horizontal_spacing": "8px",
            "columns": [
                {"tag": "column", "width": "weighted", "weight": 1,
                 "elements": [_url_button("\U0001f4cb 初审视图", first_view_url)]},
                {"tag": "column", "width": "weighted", "weight": 1,
                 "elements": [_url_button("\U0001f4cb 终审视图", final_view_url)]},
            ],
        })
    elif first_review_count > 0:
        elements.append(_url_button("\U0001f4cb 打开初审视图", first_view_url))
    else:
        elements.append(_url_button("\U0001f4cb 打开终审视图", final_view_url))

    elements.append(_hr())
    elements.append(_md("在业务表中逐条标记结论后，系统自动推进并通知业务员。", text_size="notation"))

    return _base_card(
        title="\U0001f50d 待审核任务",
        subtitle=f"共 {total} 条待审核",
        template="blue",
        tag_text="审核",
        tag_color="blue",
        elements=elements,
        summary=f"待审核任务 ｜ 初审{first_review_count}条 终审{final_review_count}条",
    )


# ---------------------------------------------------------------------------
# 3. 结果通知卡（发给业务员）
# ---------------------------------------------------------------------------

def build_result_card(
    *,
    task_type: str,
    passed: int = 0,
    rejected: int = 0,
    returned: int = 0,
    assignee_name: str = "",
    assignee_id: str = "",
    reviewer_id: str = "",
    view_url: str = "",
) -> Card:
    """通知业务员审核结果"""
    view_url = _validate_url("view_url", view_url)
    type_label = "初审" if task_type == "first" else "终审"
    assignee_name = _clean("assignee_name", assignee_name, allow_empty=True) or "业务员"

    total = passed + rejected + returned

    stats = []

    if passed > 0:
        stats.append(("✅ 通过", f"{passed} 条"))
    if rejected > 0:
        stats.append(("❌ 终止", f"{rejected} 条"))
    if returned > 0:
        stats.append(("\U0001f504 退回补充", f"{returned} 条"))

    greeting = f"{_at_user(assignee_id)}，你的{type_label}审核已完成：" if assignee_id else f"{assignee_name}，你的{type_label}审核已完成："

    if task_type == "first":
        next_label = "通过的商品进入**待二次优化**阶段，请继续完善。退回的商品请在**待补充**视图中修改后重新提交。"
    else:
        next_label = "通过的商品进入**采购阶段**。退回的商品请在**待补充**视图中修改后重新提交。"

    elements: List[Card] = [
        _md(greeting),
    ]

    if reviewer_id:
        elements.append(_hr())
        elements.append(_md(f"**审核人**：{_at_user(reviewer_id)}", text_size="notation"))

    if stats:
        elements.append(_stat_panel(stats))

    elements.append(_hr())
    elements.append(_url_button("\U0001f4ca 打开我的任务", view_url))
    elements.append(_hr())
    elements.append(_md(next_label, text_size="notation"))

    return _base_card(
        title="\U0001f4cb 审核结果",
        subtitle=f"{type_label}审核 · {total} 条",
        template="green" if rejected == 0 else "blue",
        tag_text="已完成",
        tag_color="green",
        elements=elements,
        summary=f"审核结果 ｜ {type_label} 通过{passed}/终止{rejected}/退回{returned}",
    )


# ---------------------------------------------------------------------------
# 4. 通用通知卡（阶段变更等简单通知）
# ---------------------------------------------------------------------------

def build_simple_notification_card(
    *,
    title: str,
    description: str,
    subtitle: str = "",
    template: str = "blue",
    tag_text: str = "通知",
    view_url: str = "",
    button_label: str = "\U0001f4ca 打开表格",
) -> Card:
    """通用单按钮通知卡，用于阶段变更等场景"""
    view_url = _validate_url("view_url", view_url)

    elements: List[Card] = [
        _md(description),
        _hr(),
        _url_button(button_label, view_url),
    ]

    return _base_card(
        title=title,
        subtitle=subtitle,
        template=template,
        tag_text=tag_text,
        tag_color="blue",
        elements=elements,
        summary=f"{title} ｜ {subtitle}",
    )
