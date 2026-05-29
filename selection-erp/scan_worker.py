"""
V3 定时扫描引擎 (Linux 版)

每 5 分钟扫描业务表，按阶段自动推进状态流转。
通知写入队列表后，由 notify_worker 通过 Bot 发送消息到群。
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from shared.config import (
    BASE_TOKEN,
    BUSINESS_TABLE_ID,
    TASK_TABLE_ID,
    BUSINESS_VIEWS,
    MANAGER_OPEN_IDS,
    NOTIFY_GROUP_CHAT_ID,
    load_app_secret,
)
from shared.bitable_ops import (
    BF, TF, NF,
    STAGE_DISPATCH, STAGE_FIRST_RESEARCH, STAGE_FIRST_REVIEW,
    STAGE_SECOND_OPTIMIZE, STAGE_FINAL_REVIEW,
    STAGE_SUPPLEMENT, STAGE_PURCHASE, STAGE_ENDED,
    ACTIVE_STAGES,
    NOTIFY_TYPE_DISPATCH, NOTIFY_TYPE_REVIEW, NOTIFY_TYPE_RESULT, NOTIFY_TYPE_REMINDER,
    CONCLUSION_PENDING, CONCLUSION_PASSED, CONCLUSION_REJECTED, CONCLUSION_RETURNED,
    TERMINAL_CONCLUSIONS,
    query_all_business, query_all_tasks,
    advance_stage, batch_advance_stage,
    create_task, update_task_conclusion, update_task_progress,
    enqueue_notification,
    _field_text, _field_user_id, _field_link_record_id,
)
from shared.card_v3 import (
    build_task_dispatch_card,
    build_review_notification_card,
    build_result_card,
    build_simple_notification_card,
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

SCAN_INTERVAL = 300          # 5 分钟扫描间隔
SUPPLEMENT_TIMEOUT = 600     # 待补充 10 分钟未补充 → 催办
REVIEW_NOTIFY_INTERVAL = 7200  # 审核通知间隔：2 小时
REMINDER_INTERVAL = 7200     # 催办通知间隔：2 小时
REMINDER_BEFORE_HOURS = 2    # 截止前 2 小时提醒

# 催办类型常量
REMINDER_TYPE_EXPIRING = "即将到期"
REMINDER_TYPE_EXPIRED = "已过期"

# 状态文件路径
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".review_notify_state.json")
_REMINDER_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".reminder_state.json")

# 阶段截止时间比例（基于剩余时间动态计算）
STAGE_DEADLINE_RATIOS = {
    STAGE_FIRST_RESEARCH: 2/3,
    STAGE_SECOND_OPTIMIZE: 1/2,
    STAGE_FIRST_REVIEW: 2/3,
    STAGE_FINAL_REVIEW: 1/2,
    STAGE_SUPPLEMENT: 1/2,
}

# 阶段催办接收人字段
STAGE_REMINDER_RECEIVERS = {
    STAGE_FIRST_RESEARCH: "供应链专员",
    STAGE_SECOND_OPTIMIZE: "供应链专员",
    STAGE_FIRST_REVIEW: "MANAGER",
    STAGE_FINAL_REVIEW: "MANAGER",
    STAGE_SUPPLEMENT: "供应链专员",
}

# 催办消息模板
REMINDER_TEMPLATE = "你有一条商品「{title}」{status}，请尽快处理。"

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

def _ts_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)

def _ts_ago_seconds(record: dict, field_name: str) -> float:
    val = record.get(field_name)
    if val is None:
        return 0
    if isinstance(val, (int, float)) and val > 0:
        return (_ts_now() - val) / 1000.0
    if isinstance(val, str):
        try:
            dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
            return (datetime.now() - dt).total_seconds()
        except ValueError:
            pass
    return 0

def _link_biz_id(record: dict, field_name: str) -> str:
    return _field_link_record_id([record.get(field_name)], [field_name], field_name)

def _get_deadline_ts(record: dict) -> Optional[int]:
    """获取截止时间戳（毫秒），无则返回 None"""
    val = record.get("截止时间")
    if val is None:
        return None
    if isinstance(val, (int, float)) and val > 0:
        return int(val)
    if isinstance(val, str):
        try:
            dt = datetime.strptime(val, "%Y-%m-%d %H:%M:%S")
            return int(dt.timestamp() * 1000)
        except ValueError:
            pass
    return None

def _calc_stage_deadline(record: dict, stage: str) -> Optional[int]:
    """计算阶段截止时间戳（毫秒）"""
    deadline_ts = _get_deadline_ts(record)
    if deadline_ts is None:
        return None

    ratio = STAGE_DEADLINE_RATIOS.get(stage)
    if ratio is None:
        return None

    now_ts = _ts_now()
    remaining_ms = deadline_ts - now_ts
    if remaining_ms <= 0:
        return now_ts  # 已过期

    stage_deadline = now_ts + int(remaining_ms * ratio)
    return stage_deadline

def _check_stage_reminder(record: dict, stage: str) -> Optional[Tuple[str, int]]:
    """检查阶段是否需要催办
    
    返回: (提醒类型, 阶段截止时间戳) 或 None
    """
    stage_deadline = _calc_stage_deadline(record, stage)
    if stage_deadline is None:
        return None

    now_ts = _ts_now()
    diff_seconds = (stage_deadline - now_ts) / 1000.0

    if diff_seconds < 0:
        return (REMINDER_TYPE_EXPIRED, stage_deadline)
    elif diff_seconds <= REMINDER_BEFORE_HOURS * 3600:
        return (REMINDER_TYPE_EXPIRING, stage_deadline)
    return None

# ===========================================================================
# 调研字段检查
# ===========================================================================

_FIRST_RESEARCH_FIELDS = ["供应商链接", "初步报价", "初步总成本", "预估售价"]
_SECOND_OPTIMIZE_FIELDS = ["消费者关注点", "差异化方案"]

def _check_research_fields(record: dict, stage: str) -> bool:
    """检查指定阶段的调研字段是否全部非空"""
    if stage == STAGE_FIRST_RESEARCH:
        return all(_has(record, f) for f in _FIRST_RESEARCH_FIELDS)
    if stage == STAGE_SECOND_OPTIMIZE:
        return all(_has(record, f) for f in _SECOND_OPTIMIZE_FIELDS)
    return False

# ===========================================================================
# 状态文件管理（带权限控制）
# ===========================================================================

def _ensure_file_permissions(filepath: str) -> None:
    """确保文件权限为 600"""
    if os.path.exists(filepath):
        current_mode = os.stat(filepath).st_mode & 0o777
        if current_mode != 0o600:
            os.chmod(filepath, 0o600)
            logger.debug(f"已设置文件权限: {filepath}")

def _write_state_file(filepath: str, data: dict) -> bool:
    """安全写入状态文件"""
    try:
        # 使用临时文件 + 原子重命名
        temp_file = filepath + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data, f)
        os.chmod(temp_file, 0o600)
        os.rename(temp_file, filepath)
        return True
    except IOError as e:
        logger.warning(f"写入状态文件失败 {filepath}: {e}")
        return False

def _read_state_file(filepath: str) -> dict:
    """安全读取状态文件"""
    if os.path.exists(filepath):
        _ensure_file_permissions(filepath)
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取状态文件失败 {filepath}: {e}")
    return {}

# ===========================================================================
# 催办状态管理
# ===========================================================================

def _load_reminder_state() -> Dict[str, float]:
    """加载催办状态：{receiver_id_record_id: last_remind_time}"""
    return _read_state_file(_REMINDER_STATE_FILE)

def _save_reminder_state(state: Dict[str, float]) -> None:
    """保存催办状态"""
    if not _write_state_file(_REMINDER_STATE_FILE, state):
        logger.error("保存催办状态失败")

def _get_reminder_key(receiver_id: str, record_id: str) -> str:
    """生成催办去重 key：用户 + 商品"""
    return f"{receiver_id}_{record_id}"

def _can_send_reminder(receiver_id: str, record_id: str) -> bool:
    """检查是否可以发送催办（按用户+商品去重）"""
    state = _load_reminder_state()
    key = _get_reminder_key(receiver_id, record_id)
    last_time = state.get(key, 0)
    return time.time() - last_time >= REMINDER_INTERVAL

def _mark_reminder_sent(receiver_id: str, record_id: str) -> None:
    """标记催办已发送"""
    state = _load_reminder_state()
    key = _get_reminder_key(receiver_id, record_id)
    state[key] = time.time()
    _save_reminder_state(state)

def _send_stage_reminder(record: dict, stage: str, notify_queue: List) -> None:
    """发送阶段催办通知"""
    reminder_info = _check_stage_reminder(record, stage)
    if reminder_info is None:
        return

    reminder_type, stage_deadline = reminder_info
    record_id = record.get("_record_id", "")
    title = _text(record, "商品标题") or record_id

    # 获取接收人
    receiver_field = STAGE_REMINDER_RECEIVERS.get(stage)
    if receiver_field == "MANAGER":
        receiver_id = MANAGER_OPEN_IDS[0] if MANAGER_OPEN_IDS else None
    else:
        receiver_id = _user(record, receiver_field)

    if not receiver_id:
        return

    # 检查间隔限制（按用户+商品去重）
    if not _can_send_reminder(receiver_id, record_id):
        return

    status_text = "将在 2 小时内到期" if reminder_type == REMINDER_TYPE_EXPIRING else "已过期"
    content = REMINDER_TEMPLATE.format(title=title, status=status_text)

    view_key = {
        STAGE_FIRST_RESEARCH: "pending_first",
        STAGE_SECOND_OPTIMIZE: "pending_second",
        STAGE_FIRST_REVIEW: "pending_review",
        STAGE_FINAL_REVIEW: "pending_final",
        STAGE_SUPPLEMENT: "pending_supply",
    }.get(stage, "pending_dispatch")

    notify_queue.append((NOTIFY_TYPE_REMINDER, receiver_id, content, {
        "text": content,
        "view_url": BUSINESS_VIEWS.get(view_key, ""),
        "reminder_type": reminder_type,
    }))

    _mark_reminder_sent(receiver_id, record_id)
    logger.info(f"  [{stage}-{reminder_type}] {title} → {receiver_id}")

# ===========================================================================
# 通知聚合
# ===========================================================================

def _flush_notifications(queued: List[Tuple[str, str, str, dict]]) -> None:
    """聚合去重，构建卡片 JSON，写入通知队列表"""
    by_key: Dict[Tuple[str, str], dict] = defaultdict(lambda: {"texts": [], "infos": []})
    for ntype, uid, text, card_info in queued:
        by_key[(ntype, uid)]["texts"].append(text)
        if card_info:
            by_key[(ntype, uid)]["infos"].append(card_info)

    for (ntype, uid), data in by_key.items():
        merged_text = "\n---\n".join(data["texts"])
        card = _build_aggregated_card(ntype, uid, data["infos"])
        payload = json.dumps({"text": merged_text, "card": card}, ensure_ascii=False)
        nid = enqueue_notification(ntype, uid, payload)
        if nid:
            logger.info(f"  [通知队列] {ntype} → {uid}")
        else:
            logger.error(f"  [通知-失败] {ntype} → {uid}")

def _build_aggregated_card(ntype: str, uid: str, infos: List[dict]) -> dict:
    """根据聚合后的 card_info 列表构建单张卡片"""
    if not infos:
        return build_simple_notification_card(
            title="选品ERP通知",
            description="有新的通知，请在业务表中查看详情。",
            subtitle=ntype,
            view_url=BUSINESS_VIEWS.get("pending_dispatch", ""),
        )

    info = infos[0]

    if ntype == NOTIFY_TYPE_DISPATCH:
        return build_task_dispatch_card(
            task_type=info.get("task_type", "first"),
            count=info.get("count", 0),
            assignee_name=info.get("assignee_name", ""),
            assignee_id=uid,
            view_url=info.get("view_url", ""),
        )
    elif ntype == NOTIFY_TYPE_REVIEW:
        first_count = info.get("first_count", 0)
        final_count = info.get("final_count", 0)
        first_returned = info.get("first_returned", 0)
        final_returned = info.get("final_returned", 0)
        new_first = max(0, first_count - first_returned)
        new_final = max(0, final_count - final_returned)
        return build_review_notification_card(
            first_review_count=new_first,
            first_returned=first_returned,
            final_review_count=new_final,
            final_returned=final_returned,
            first_view_url=info.get("first_view_url", ""),
            final_view_url=info.get("final_view_url", ""),
            reviewer_ids=info.get("reviewer_ids"),
        )
    elif ntype == NOTIFY_TYPE_RESULT:
        first_data = info.get("first", {})
        final_data = info.get("final", {})
        cards = []
        if any(first_data.get(k, 0) > 0 for k in ["passed", "rejected", "returned"]):
            cards.append(build_result_card(
                task_type="first",
                passed=first_data.get("passed", 0),
                rejected=first_data.get("rejected", 0),
                returned=first_data.get("returned", 0),
                assignee_id=uid,
                view_url=info.get("view_url", ""),
            ))
        if any(final_data.get(k, 0) > 0 for k in ["passed", "rejected", "returned"]):
            cards.append(build_result_card(
                task_type="final",
                passed=final_data.get("passed", 0),
                rejected=final_data.get("rejected", 0),
                returned=final_data.get("returned", 0),
                assignee_id=uid,
                view_url=info.get("view_url", ""),
            ))
        if cards:
            return cards[0] if len(cards) == 1 else build_result_card(
                task_type="final",
                passed=first_data.get("passed", 0) + final_data.get("passed", 0),
                rejected=first_data.get("rejected", 0) + final_data.get("rejected", 0),
                returned=first_data.get("returned", 0) + final_data.get("returned", 0),
                assignee_id=uid,
                view_url=info.get("view_url", ""),
            )
        return build_simple_notification_card(
            title="审核结果",
            description="审核已完成，请在业务表中查看详情。",
            subtitle="审核",
            view_url=info.get("view_url", ""),
        )
    elif ntype == NOTIFY_TYPE_REMINDER:
        return build_simple_notification_card(
            title="待补充催办",
            description=info.get("text", "你有商品超时未补充，请尽快处理。"),
            subtitle="催办",
            tag_text="催办",
            view_url=info.get("view_url", ""),
        )
    else:
        return build_simple_notification_card(
            title="选品ERP通知",
            description=info.get("text", "请在业务表中查看详情。"),
            subtitle=ntype,
            view_url=info.get("view_url", ""),
        )

# ===========================================================================
# 阶段处理
# ===========================================================================

def process_dispatch(records: List[dict], notify_queue: List) -> None:
    """待派发 → 待初步调研"""
    stage_records = [r for r in records if _text(r, "当前阶段") == STAGE_DISPATCH]
    if not stage_records:
        return

    by_assignee: Dict[str, List[str]] = defaultdict(list)
    for r in stage_records:
        if not _has(r, "商品链接"):
            logger.info(f"  [派发-跳过] {r['_record_id']}: 商品链接为空")
            continue
        uid = _user(r, "供应链专员")
        if not uid:
            logger.info(f"  [派发-跳过] {r['_record_id']}: 供应链专员为空")
            continue
        by_assignee[uid].append(r["_record_id"])

    for uid, rids in by_assignee.items():
        ok = batch_advance_stage(rids, STAGE_FIRST_RESEARCH)
        if ok:
            logger.info(f"  [派发] {len(rids)} 条 → 待初步调研, 业务员={uid}")
            notify_queue.append((NOTIFY_TYPE_DISPATCH, uid,
                     f"你有 {len(rids)} 条新商品需进行调研。"
                     f"请在业务表「待初步调研」视图中填写供应商链接、报价、成本、售价。",
                     {"task_type": "first", "count": len(rids),
                      "assignee_name": uid, "view_url": BUSINESS_VIEWS["pending_first"]}))


def process_first_research(records: List[dict], tasks: List[dict], notify_queue: List) -> None:
    """待初步调研 → 待初审"""
    _process_research_stage(records, tasks, STAGE_FIRST_RESEARCH, STAGE_FIRST_REVIEW,
                            "初审", "初审", notify_queue)


def process_second_optimize(records: List[dict], tasks: List[dict], notify_queue: List) -> None:
    """待二次优化 → 待终审"""
    _process_research_stage(records, tasks, STAGE_SECOND_OPTIMIZE, STAGE_FINAL_REVIEW,
                            "终审", "终审", notify_queue)


def _process_research_stage(
    records: List[dict],
    tasks: List[dict],
    from_stage: str,
    to_stage: str,
    task_type: str,
    type_label: str,
    notify_queue: List,
) -> None:
    """通用调研阶段处理"""
    stage_records = [r for r in records if _text(r, "当前阶段") == from_stage]
    if not stage_records:
        return

    for r in stage_records:
        rid = r["_record_id"]
        title = _text(r, "商品标题") or rid

        if not _check_research_fields(r, from_stage):
            _send_stage_reminder(r, from_stage, notify_queue)
            age = _ts_ago_seconds(r, "最后更新时间")
            if age > SUPPLEMENT_TIMEOUT:
                logger.info(f"  [{from_stage}-超时] {title}: {age:.0f}s 未完成填写")
            continue

        task_name = f"{type_label}-{title}"
        task_id = create_task(
            name=task_name,
            task_type=task_type,
            assignee_id=MANAGER_OPEN_IDS[0],
            business_id=rid,
        )
        if not task_id:
            logger.error(f"  [{from_stage}] 创建任务失败: {title}")
            continue

        ok = advance_stage(rid, to_stage)
        if ok:
            logger.info(f"  [{from_stage}] {title} → {to_stage}, 任务={task_id}")

    ready = [r for r in stage_records if _check_research_fields(r, from_stage)]
    if ready:
        notify_queue.append((NOTIFY_TYPE_REVIEW, MANAGER_OPEN_IDS[0],
                 f"{type_label}任务已生成 {len(ready)} 条，"
                 f"请在业务表「{from_stage if from_stage != STAGE_SECOND_OPTIMIZE else '待二次优化'}」视图中审核。",
                 {"first_count": len(ready) if task_type == "初审" else 0,
                  "final_count": len(ready) if task_type == "终审" else 0,
                  "first_view_url": BUSINESS_VIEWS["pending_review"],
                  "final_view_url": BUSINESS_VIEWS["pending_final"],
                  "reviewer_ids": MANAGER_OPEN_IDS}))


def process_first_review(records: List[dict], tasks: List[dict], biz_to_task: Dict, notify_queue: List) -> dict:
    """待初审 → 继续/终止/退回补充"""
    return _process_review_stage(
        records, tasks, biz_to_task, notify_queue,
        from_stage=STAGE_FIRST_REVIEW,
        conclusion_field="初审结论",
        pass_value="继续",
        reject_value="终止",
        return_value="退回补充",
        pass_stage=STAGE_SECOND_OPTIMIZE,
        reject_stage=STAGE_ENDED,
        return_stage=STAGE_SUPPLEMENT,
        task_type_label="初审",
    )


def process_final_review(records: List[dict], tasks: List[dict], biz_to_task: Dict, notify_queue: List) -> dict:
    """待终审 → 通过/不通过/退回优化"""
    return _process_review_stage(
        records, tasks, biz_to_task, notify_queue,
        from_stage=STAGE_FINAL_REVIEW,
        conclusion_field="终审结论",
        pass_value="通过",
        reject_value="不通过",
        return_value="退回优化",
        pass_stage=STAGE_PURCHASE,
        reject_stage=STAGE_ENDED,
        return_stage=STAGE_SUPPLEMENT,
        task_type_label="终审",
    )


def _process_review_stage(
    records: List[dict],
    tasks: List[dict],
    biz_to_task: Dict,
    notify_queue: List,
    from_stage: str,
    conclusion_field: str,
    pass_value: str,
    reject_value: str,
    return_value: str,
    pass_stage: str,
    reject_stage: str,
    return_stage: str,
    task_type_label: str,
) -> Dict[str, Dict[str, List[str]]]:
    """通用审核阶段处理"""
    stage_records = [r for r in records if _text(r, "当前阶段") == from_stage]
    results: Dict[str, Dict[str, List[str]]] = defaultdict(
        lambda: {"passed": [], "rejected": [], "returned": []})

    if not stage_records:
        return results

    for r in stage_records:
        conclusion = _text(r, conclusion_field)
        rid = r["_record_id"]
        title = _text(r, "商品标题") or rid

        if not conclusion:
            _send_stage_reminder(r, from_stage, notify_queue)
            continue

        assignee_id = _user(r, "供应链专员")

        # 幂等检查：检查任务结论 + 业务表阶段
        task = biz_to_task.get(rid)
        task_conclusion = _text(task, "处理结论") if task else ""
        current_stage = _text(r, "当前阶段")
        
        if task_conclusion in TERMINAL_CONCLUSIONS and current_stage != from_stage:
            logger.info(f"  [{from_stage}-跳过] {title}: 已处理（任务已终局且阶段已变更）")
            continue

        if conclusion == pass_value:
            advance_stage(rid, pass_stage)
            _update_task_for_biz(rid, biz_to_task, CONCLUSION_PASSED)
            if assignee_id:
                results[assignee_id]["passed"].append(rid)
            logger.info(f"  [{from_stage}] {title}: 通过 → {pass_stage}")

        elif conclusion == reject_value:
            advance_stage(rid, reject_stage)
            _update_task_for_biz(rid, biz_to_task, CONCLUSION_REJECTED)
            if assignee_id:
                results[assignee_id]["rejected"].append(rid)
            logger.info(f"  [{from_stage}] {title}: 终止 → {reject_stage}")

        elif conclusion == return_value:
            advance_stage(rid, return_stage)
            _update_task_for_biz(rid, biz_to_task, CONCLUSION_RETURNED)
            if assignee_id:
                results[assignee_id]["returned"].append(rid)
            logger.info(f"  [{from_stage}] {title}: 退回 → {return_stage}")

    # 检查任务完成条件
    for t in tasks:
        if _text(t, "进展") == "已完成":
            continue
        conclusion = _text(t, "处理结论")
        if conclusion in TERMINAL_CONCLUSIONS:
            update_task_progress(t["_record_id"], "已完成")
            logger.info(f"  [任务完成] {_text(t, '任务名称')}")

    return results


def _update_task_for_biz(biz_id: str, biz_to_task: dict, conclusion: str) -> None:
    """更新业务记录关联任务的结论"""
    task = biz_to_task.get(biz_id)
    if task:
        update_task_conclusion(task["_record_id"], conclusion)


def process_supplement(records: List[dict], tasks: List[dict], biz_to_task: Dict, notify_queue: List) -> None:
    """待补充 → 回审"""
    stage_records = [r for r in records if _text(r, "当前阶段") == STAGE_SUPPLEMENT]
    if not stage_records:
        return

    # 预先构建 biz_id -> task 映射（从传入的 tasks）
    task_biz_map: Dict[str, dict] = {}
    for t in tasks:
        linked = _link_biz_id(t, "关联商品")
        if linked:
            task_biz_map[linked] = t

    for r in stage_records:
        rid = r["_record_id"]
        title = _text(r, "商品标题") or rid
        assignee_id = _user(r, "供应链专员")

        if _has(r, "补充完成") and _text(r, "补充完成") == "是":
            task = task_biz_map.get(rid)
            back_stage = ""
            
            if task and _text(task, "处理结论") == CONCLUSION_RETURNED:
                if _text(task, "任务类型") == "初审":
                    back_stage = STAGE_FIRST_REVIEW
                elif _text(task, "任务类型") == "终审":
                    back_stage = STAGE_FINAL_REVIEW

            if back_stage:
                extra = {"补充完成": "否"}
                if back_stage == STAGE_FIRST_REVIEW:
                    extra["初审结论"] = ""
                elif back_stage == STAGE_FINAL_REVIEW:
                    extra["终审结论"] = ""
                ok = advance_stage(rid, back_stage, extra_fields=extra)
                if ok:
                    logger.info(f"  [待补充→{back_stage}] {title}: 补充完成，回审")
                    if task:
                        update_task_conclusion(task["_record_id"], CONCLUSION_PENDING)
            else:
                logger.warning(f"  [待补充-跳过] {title}: 无法判断退回来源")
            continue

        _send_stage_reminder(r, STAGE_SUPPLEMENT, notify_queue)

# ===========================================================================
# 审核通知（拆分后的辅助函数）
# ===========================================================================

def _count_review_records(records: List[dict]) -> Tuple[int, int]:
    """统计待审核记录数"""
    first_review = sum(1 for r in records if _text(r, "当前阶段") == STAGE_FIRST_REVIEW)
    final_review = sum(1 for r in records if _text(r, "当前阶段") == STAGE_FINAL_REVIEW)
    return first_review, final_review


def _count_returned_tasks(tasks: List[dict]) -> Tuple[int, int]:
    """统计退回任务数"""
    returned_first = sum(1 for t in tasks
                         if _text(t, "任务类型") == "初审"
                         and _text(t, "处理结论") == CONCLUSION_RETURNED)
    returned_final = sum(1 for t in tasks
                         if _text(t, "任务类型") == "终审"
                         and _text(t, "处理结论") == CONCLUSION_RETURNED)
    return returned_first, returned_final


def _should_send_review_notification(new_first: int, new_final: int, 
                                      returned_first: int, returned_final: int) -> Tuple[bool, float]:
    """判断是否应发送审核通知
    
    修复逻辑：
    1. 有新待审记录时发送
    2. 退回记录增加时发送
    3. 距离上次发送超过间隔
    """
    if new_first == 0 and new_final == 0 and returned_first == 0 and returned_final == 0:
        return False, 0.0

    now_ts = time.time()
    last_state = _read_state_file(_STATE_FILE)
    
    last_first = last_state.get("first_count", 0)
    last_final = last_state.get("final_count", 0)
    last_returned_first = last_state.get("returned_first", 0)
    last_returned_final = last_state.get("returned_final", 0)
    last_time = last_state.get("last_notify_time", 0)

    # 新待审数增加 或 退回数增加
    new_first_increased = new_first > last_first
    new_final_increased = new_final > last_final
    returned_increased = (returned_first > last_returned_first or returned_final > last_returned_final)
    
    time_elapsed = now_ts - last_time

    should_send = (new_first_increased or new_final_increased or returned_increased) and time_elapsed >= REVIEW_NOTIFY_INTERVAL
    
    return should_send, now_ts


def _update_review_state(new_first: int, new_final: int, 
                         returned_first: int, returned_final: int, 
                         last_time: float, should_send: bool) -> None:
    """更新审核通知状态"""
    current_state = {
        "first_count": new_first,
        "final_count": new_final,
        "returned_first": returned_first,
        "returned_final": returned_final,
        "last_notify_time": last_time if not should_send else time.time()
    }
    if not _write_state_file(_STATE_FILE, current_state):
        logger.error("保存审核通知状态失败")


def _send_review_notifications(records: List[dict], tasks: List[dict], notify_queue: List) -> None:
    """统计待审核记录，按主管聚合并入队"""
    total_first, total_final = _count_review_records(records)
    returned_first, returned_final = _count_returned_tasks(tasks)
    
    new_first = max(0, total_first - returned_first)
    new_final = max(0, total_final - returned_final)

    should_send, now_ts = _should_send_review_notification(
        new_first, new_final, returned_first, returned_final
    )
    
    _update_review_state(new_first, new_final, returned_first, returned_final, 
                         now_ts, should_send)

    if not should_send:
        return

    parts = []
    if new_first > 0:
        parts.append(f"待初审 {new_first} 条")
    total_returned = returned_first + returned_final
    if total_returned > 0:
        parts.append(f"退回重审 {total_returned} 条")
    if new_final > 0:
        parts.append(f"待终审 {new_final} 条")

    if parts:
        content = "请审核以下任务：" + "，".join(parts) + "。请在业务表中填写审核结论。"
        for mgr_id in MANAGER_OPEN_IDS:
            notify_queue.append((NOTIFY_TYPE_REVIEW, mgr_id, content,
                     {"first_count": total_first, "first_returned": returned_first,
                      "final_count": total_final, "final_returned": returned_final,
                      "first_view_url": BUSINESS_VIEWS["pending_review"],
                      "final_view_url": BUSINESS_VIEWS["pending_final"],
                      "reviewer_ids": [mgr_id]}))
        logger.info(f"  [审核通知] → 主管: {'，'.join(parts)}")


def _send_result_notifications(
    first_results: Dict[str, Dict[str, List[str]]],
    final_results: Dict[str, Dict[str, List[str]]],
    notify_queue: List,
) -> None:
    """按专员聚合并入队审核结果通知"""
    all_assignees = set(list(first_results.keys()) + list(final_results.keys()))

    for uid in all_assignees:
        fst = first_results.get(uid, {"passed": [], "rejected": [], "returned": []})
        fnl = final_results.get(uid, {"passed": [], "rejected": [], "returned": []})

        parts = []
        if fst["passed"]:
            parts.append(f"初审通过 {len(fst['passed'])} 条")
        if fst["rejected"]:
            parts.append(f"初审终止 {len(fst['rejected'])} 条")
        if fst["returned"]:
            parts.append(f"初审退回 {len(fst['returned'])} 条")
        if fnl["passed"]:
            parts.append(f"终审通过 {len(fnl['passed'])} 条")
        if fnl["rejected"]:
            parts.append(f"终审不通过 {len(fnl['rejected'])} 条")
        if fnl["returned"]:
            parts.append(f"终审退回 {len(fnl['returned'])} 条")

        if parts:
            content = "你的审核结果：\n" + "\n".join(parts) + "\n请在业务表中查看详情。"
            card_info = {
                "first": {"passed": len(fst["passed"]), "rejected": len(fst["rejected"]), "returned": len(fst["returned"])},
                "final": {"passed": len(fnl["passed"]), "rejected": len(fnl["rejected"]), "returned": len(fnl["returned"])},
                "view_url": BUSINESS_VIEWS["pending_first"],
            }
            notify_queue.append((NOTIFY_TYPE_RESULT, uid, content, card_info))
            logger.info(f"  [结果通知] → {uid}: {'，'.join(parts)}")

# ===========================================================================
# 异常分类
# ===========================================================================

class RecoverableError(Exception):
    """可恢复异常：网络抖动、API限流等，等待后可继续"""
    pass


class FatalError(Exception):
    """致命异常：配置错误、权限问题等，需要人工介入"""
    pass


def _classify_exception(e: Exception) -> bool:
    """判断异常是否可恢复
    
    Returns:
        True: 可恢复，继续运行
        False: 致命错误，应终止进程
    """
    error_str = str(e).lower()
    
    # 可恢复的情况
    if any(keyword in error_str for keyword in ["timeout", "connection", "network", "rate limit"]):
        return True
    
    # 致命错误
    if any(keyword in error_str for keyword in ["permission", "auth", "forbidden", "unauthorized"]):
        return False
    
    # 其他情况保守处理：可恢复
    return True

# ===========================================================================
# 主循环
# ===========================================================================

def scan_cycle() -> None:
    """执行一次完整扫描"""
    notify_queue: List[Tuple[str, str, str, dict]] = []

    logger.info("=" * 60)
    logger.info(f"[扫描] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    logger.info("[查询] 业务表…")
    records = query_all_business()
    logger.info(f"  → {len(records)} 条记录")

    if not records:
        return

    # 统一查询任务表，避免重复查询
    logger.info("[查询] 任务表…")
    tasks = query_all_tasks()
    logger.info(f"  → {len(tasks)} 条记录")

    # 构建 biz_id -> task 映射
    biz_to_task: Dict[str, dict] = {}
    for t in tasks:
        linked = _link_biz_id(t, "关联商品")
        if linked:
            biz_to_task[linked] = t

    # 6 个处理阶段，顺序执行
    logger.info("[阶段] 待派发…")
    process_dispatch(records, notify_queue)

    logger.info("[阶段] 待初步调研…")
    process_first_research(records, tasks, notify_queue)

    logger.info("[阶段] 待二次优化…")
    process_second_optimize(records, tasks, notify_queue)

    logger.info("[阶段] 待初审…")
    first_results = process_first_review(records, tasks, biz_to_task, notify_queue)

    logger.info("[阶段] 待终审…")
    final_results = process_final_review(records, tasks, biz_to_task, notify_queue)

    logger.info("[阶段] 待补充…")
    process_supplement(records, tasks, biz_to_task, notify_queue)

    # 发送审核通知
    _send_review_notifications(records, tasks, notify_queue)

    # 发送结果通知
    _send_result_notifications(first_results, final_results, notify_queue)

    # 清空通知队列
    if notify_queue:
        logger.info("[通知] 写入通知队列表…")
        _flush_notifications(notify_queue)

    # 发送消息通知到群
    try:
        from notify_worker import flush_pending_notifications
        flush_pending_notifications()
    except ImportError as e:
        logger.error(f"[通知] notify_worker 导入失败: {e}")
        logger.error("[通知] 通知队列已写入，但消息未发送，请手动运行 notify_worker.py")
    except Exception as e:
        logger.error(f"[通知] 发送消息失败: {e}")

    logger.info(f"[扫描完成] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


def main() -> None:
    load_app_secret()

    logger.info("=" * 60)
    logger.info("V3 扫描引擎启动 (Linux)")
    logger.info(f"扫描间隔: {SCAN_INTERVAL}s (5分钟)")
    logger.info(f"业务表: {BUSINESS_TABLE_ID}")
    logger.info(f"任务表: {TASK_TABLE_ID}")
    logger.info(f"主管: {MANAGER_OPEN_IDS}")
    logger.info("=" * 60)

    scan_cycle()

    consecutive_errors = 0
    max_consecutive_errors = 3

    while True:
        logger.info(f"\n[等待] {SCAN_INTERVAL}s 后下次扫描…")
        time.sleep(SCAN_INTERVAL)
        try:
            scan_cycle()
            consecutive_errors = 0  # 成功后重置计数
        except Exception as e:
            consecutive_errors += 1
            logger.error(f"[ERROR] 扫描异常 ({consecutive_errors}/{max_consecutive_errors}): {e}")
            
            import traceback
            traceback.print_exc()
            
            if not _classify_exception(e):
                logger.critical(f"[FATAL] 致命错误，终止进程: {e}")
                sys.exit(1)
            
            if consecutive_errors >= max_consecutive_errors:
                logger.critical(f"[FATAL] 连续 {max_consecutive_errors} 次异常，终止进程")
                sys.exit(1)
            
            logger.warning(f"[WARN] 等待 30s 后重试")
            time.sleep(30)


if __name__ == "__main__":
    main()
