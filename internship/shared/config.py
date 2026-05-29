"""实习工时模块配置"""
import os
import logging

logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
                            v = v.strip()
                            if v.startswith('"') and v.endswith('"'):
                                v = v[1:-1]
                            elif v.startswith("'") and v.endswith("'"):
                                v = v[1:-1]
                            return v
        except IOError as e:
            logger.warning(f"读取 .env 文件失败: {e}")

    return default


def _load_env_required(key: str) -> str:
    """加载必需的环境变量"""
    value = _load_env_or_default(key, "")
    if not value:
        raise ValueError(f"必需的环境变量 {key} 未配置")
    return value


# ===========================================================================
# 多维表格配置
# ===========================================================================

BASE_TOKEN = _load_env_required("FEISHU_BASE_TOKEN")
CLI_PROFILE = _load_env_or_default("FEISHU_CLI_PROFILE", "")

WEEKLY_ATTENDANCE_TABLE_ID = _load_env_or_default("WEEKLY_ATTENDANCE_TABLE_ID", "")
MONTHLY_SUMMARY_TABLE_ID = _load_env_or_default("MONTHLY_SUMMARY_TABLE_ID", "")

BASE_URL = f"https://jcnj2ogjcmym.feishu.cn/base/{BASE_TOKEN}"
WEEKLY_TABLE_URL = f"{BASE_URL}?table={WEEKLY_ATTENDANCE_TABLE_ID}" if WEEKLY_ATTENDANCE_TABLE_ID else ""
MONTHLY_TABLE_URL = f"{BASE_URL}?table={MONTHLY_SUMMARY_TABLE_ID}" if MONTHLY_SUMMARY_TABLE_ID else ""


def load_app_secret() -> str:
    """加载应用密钥"""
    return _load_env_or_default("FEISHU_APP_SECRET", "")


# ===========================================================================
# 扫描配置
# ===========================================================================

SCAN_INTERVAL_SECONDS = 300
MAX_CONSECUTIVE_ERRORS = 3
RETRY_DELAY_SECONDS = 30

# ===========================================================================
# 定时任务触发时间
# ===========================================================================

CREATE_RECORD_HOUR = 14
CREATE_RECORD_MINUTE = 0

REMIND_HOUR = 21
REMIND_MINUTE = 0

AUTO_CONFIRM_HOUR = 23
AUTO_CONFIRM_MINUTE = 59

SUMMARY_DAY = 1
SUMMARY_HOUR = 0
SUMMARY_MINUTE = 0

# ===========================================================================
# 出勤状态常量
# ===========================================================================

STATUS_DRAFT = "待填写"
STATUS_PENDING = "待确认"
STATUS_CONFIRMED = "已确认"

SUMMARY_DRAFT = "待提交"
SUMMARY_PENDING = "待审批"
SUMMARY_PASSED = "已通过"
SUMMARY_REJECTED = "已退回"

ATTENDANCE_FULL = "全天"
ATTENDANCE_AM = "上午"
ATTENDANCE_PM = "下午"
ATTENDANCE_NONE = "无"

# ===========================================================================
# 日历配置
# ===========================================================================

CALENDAR_ID = _load_env_or_default("CALENDAR_ID", "")
