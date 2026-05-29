"""飞书 API 封装：CLI 调用（Linux 版）"""
import json
import subprocess
import logging
from typing import Any, Dict, Optional

from .config import LARK_CLI, APP_ID, CLI_PROFILE

logger = logging.getLogger(__name__)

# 允许的 lark-cli 命令白名单
ALLOWED_COMMANDS = {
    "base", "im", "auth", "drive", "wiki", "docx", "sheets", "bitable"
}

# 允许的子命令白名单
ALLOWED_SUBCOMMANDS = {
    "+record-list", "+record-upsert", "+field-list", "+messages-send",
    "+login", "+whoami", "status", "login"
}


def _validate_args(args: tuple) -> bool:
    """验证参数是否在白名单内"""
    if not args:
        return True
    cmd = args[0] if args else ""
    subcmd = args[1] if len(args) > 1 else ""
    
    if cmd and cmd not in ALLOWED_COMMANDS:
        logger.warning(f"不允许的命令: {cmd}")
        return False
    if subcmd and subcmd not in ALLOWED_SUBCOMMANDS and not subcmd.startswith("--"):
        logger.warning(f"不允许的子命令: {subcmd}")
        return False
    return True


def run_cli(*args) -> Optional[Dict[str, Any] | str]:
    """调用 lark-cli，返回解析后的 JSON 或原始字符串
    
    Args:
        *args: lark-cli 命令参数
        
    Returns:
        解析后的 JSON 字典，或原始字符串输出。失败返回 None。
    """
    # 参数验证
    if not _validate_args(args):
        logger.error(f"参数验证失败: {args}")
        return None
    
    cmd = [LARK_CLI, "--profile", CLI_PROFILE] + list(args)
    label = args[0] + (f" {args[1]}" if len(args) > 1 else "")
    logger.debug(f"执行命令: lark-cli {label}")
    
    try:
        result = subprocess.run(
            cmd, 
            capture_output=True, 
            text=True, 
            timeout=30,
            encoding="utf-8", 
            errors="replace",
            shell=False  # 显式禁用 shell
        )
    except subprocess.TimeoutExpired:
        logger.error(f"命令超时: lark-cli {label}")
        return None
    except subprocess.SubprocessError as e:
        logger.error(f"子进程错误: {e}")
        return None
    
    if result.returncode != 0:
        err = (result.stderr or "")[:300]
        logger.error(f"命令失败: {err}")
        return None
    
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return result.stdout if result.stdout else None
