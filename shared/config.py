"""公共配置：Base 常量、URL 构建、密钥加载"""
import os
import logging

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# lark-cli 路径
LARK_CLI = "lark-cli"


def _load_env_or_default(key: str, default: str = "") -> str:
    """从环境变量加载配置，支持 .env 文件"""
    value = os.environ.get(key, "")
    if value:
        return value

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


# ===========================================================================
# 多维表格配置
# ===========================================================================

BASE_TOKEN = _load_env_or_default("FEISHU_BASE_TOKEN", "WpFzbIX13aEhhNs3ZXgc67gqnjf")
APP_ID = _load_env_or_default("FEISHU_APP_ID", "")
CLI_PROFILE = _load_env_or_default("FEISHU_CLI_PROFILE", "")

EXPENSE_TABLE_ID = _load_env_or_default("EXPENSE_TABLE_ID", "tblcZqBKOzmfDqFH")

BASE_URL = f"https://jcnj2ogjcmym.feishu.cn/base/{BASE_TOKEN}"
EXPENSE_TABLE_URL = f"{BASE_URL}?table={EXPENSE_TABLE_ID}"


def load_app_secret() -> str:
    """从环境变量或 .env 文件加载 APP_SECRET"""
    return _load_env_or_default("FEISHU_APP_SECRET", "")
