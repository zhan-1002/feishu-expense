"""公共配置：Base 常量、URL 构建、密钥加载（Linux 版）"""
import os
import logging

# 配置日志
logger = logging.getLogger(__name__)

# 项目根目录（config.py 在 shared/ 下，往上 1 层）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# lark-cli 路径（Linux 下通过 npm 全局安装，位于 PATH 中）
LARK_CLI = "lark-cli"


def _load_env_or_default(key: str, default: str = "") -> str:
    """从环境变量加载配置，支持 .env 文件"""
    # 先尝试从环境变量获取
    value = os.environ.get(key, "")
    if value:
        return value
    
    # 尝试从 .env 文件加载
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        if k.strip() == key:
                            return v.strip()
        except IOError as e:
            logger.warning(f"读取 .env 文件失败: {e}")
    
    return default


def _load_list_env(key: str, default: list = None) -> list:
    """加载逗号分隔的列表配置"""
    if default is None:
        default = []
    value = _load_env_or_default(key, "")
    if not value:
        return default
    return [item.strip() for item in value.split(",") if item.strip()]


# ===========================================================================
# 当前使用的工作区 — 新工作区 (jcnj2ogjcmym.feishu.cn)
# ===========================================================================

BASE_TOKEN = _load_env_or_default("FEISHU_BASE_TOKEN", "LqiOb2IsDaLv3Es7aAycyAN1nXd")
APP_ID = _load_env_or_default("FEISHU_APP_ID", "cli_aa9ebe24072a9bda")
CLI_PROFILE = _load_env_or_default("FEISHU_CLI_PROFILE", "cli_aa9ebe24072a9bda")

# 选品主管列表（open_id），扫描脚本通知审核时使用
MANAGER_OPEN_IDS = _load_list_env("MANAGER_OPEN_IDS", ["ou_f07afee875c9fc1afecb76469a4ff9fc"])

BASE_URL = f"https://jcnj2ogjcmym.feishu.cn/base/{BASE_TOKEN}"

# 通知群 chat_id（Bot 已在此群中，脚本发消息通知用）
NOTIFY_GROUP_CHAT_ID = _load_env_or_default("NOTIFY_GROUP_CHAT_ID", "oc_c5904b4b9e2f777282acae3b2e31b35d")

# ===========================================================================
# V3 三表架构
# ===========================================================================

BUSINESS_TABLE_ID = "tbliGZGFhM8nmAec"       # 选品业务表（唯一人工操作）
TASK_TABLE_ID = "tblZNPcOeChP8zhu"           # 任务表（脚本管理，含关联商品+处理结论）
NOTIFY_TABLE_ID = "tblwyUg7FUfpAlgY"         # 通知队列表（脚本写入，notify_worker 发送）

BUSINESS_TABLE_URL = f"{BASE_URL}?table={BUSINESS_TABLE_ID}"
TASK_TABLE_URL = f"{BASE_URL}?table={TASK_TABLE_ID}"
NOTIFY_TABLE_URL = f"{BASE_URL}?table={NOTIFY_TABLE_ID}"

# --- 业务表视图 ---
BUSINESS_VIEWS = {
    "pending_dispatch": f"{BUSINESS_TABLE_URL}&view=vewvyCWxaH",   # 待派发
    "pending_first":    f"{BUSINESS_TABLE_URL}&view=vewkXDtWyo",   # 待初步调研
    "pending_review":   f"{BUSINESS_TABLE_URL}&view=vewtWwdsgI",   # 待初审
    "pending_second":   f"{BUSINESS_TABLE_URL}&view=vewOXP6Kr0",   # 待二次优化
    "pending_final":    f"{BUSINESS_TABLE_URL}&view=vewcBdpdwE",   # 待终审
    "pending_supply":   f"{BUSINESS_TABLE_URL}&view=vewXwroP42",   # 待补充
    "ended":            f"{BUSINESS_TABLE_URL}&view=vewbli8LEA",   # 已结束
}

# --- 任务表视图 ---
TASK_VIEWS = {
    "all":        f"{TASK_TABLE_URL}&view=vewR7GLMkf",
    "my_tasks":   f"{TASK_TABLE_URL}&view=vew0ySPtWJ",
    "in_progress": f"{TASK_TABLE_URL}&view=vewkTCc8nf",
}

# --- 通知队列表视图 ---
NOTIFY_VIEWS = {
    "all":       f"{NOTIFY_TABLE_URL}&view=vew_PLACEHOLDER",
    "pending":   f"{NOTIFY_TABLE_URL}&view=vew_PLACEHOLDER_PENDING",
}


def load_app_secret() -> str:
    """从环境变量或 .env 文件加载 APP_SECRET，返回字符串"""
    return _load_env_or_default("FEISHU_APP_SECRET", "")
