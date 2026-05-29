"""飞书 API 封装：lark-cli 调用（公共）"""
import json
import logging
import subprocess
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

ALLOWED_COMMANDS = {
    "base", "im", "auth", "drive", "wiki", "docx", "sheets", "bitable",
}

ALLOWED_SUBCOMMANDS = {
    "+record-list", "+record-upsert", "+field-list", "+messages-send",
    "+login", "+whoami", "status", "login",
}

DEFAULT_TIMEOUT_SECONDS = 60
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2


def _validate_args(args: tuple) -> bool:
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


def _get_lark_cli():
    import os
    return os.environ.get("LARK_CLI", "lark-cli")


def _get_cli_profile():
    import os
    return os.environ.get("FEISHU_CLI_PROFILE", "")


def run_cli(*args: str, timeout: Optional[int] = None,
            max_retries: int = MAX_RETRIES) -> Optional[Dict[str, Any]]:
    if not _validate_args(args):
        logger.error(f"参数验证失败: {args}")
        return None

    timeout = timeout or DEFAULT_TIMEOUT_SECONDS
    lark_cli = _get_lark_cli()
    profile = _get_cli_profile()

    cmd = [lark_cli]
    if profile:
        cmd.extend(["--profile", profile])
    cmd.extend(args)

    label = args[0] + (f" {args[1]}" if len(args) > 1 else "")

    last_error: Optional[str] = None

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
                shell=False,
            )

            if result.returncode != 0:
                last_error = (result.stderr or "")[:300]
                if "timeout" not in result.stderr.lower() and "connection" not in result.stderr.lower():
                    logger.error(f"lark-cli 错误: {last_error}")
                    return None
                if attempt < max_retries - 1:
                    delay = RETRY_DELAY_BASE ** (attempt + 1)
                    logger.warning(f"lark-cli 调用失败，{delay}s 后重试 ({attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                return None

            stdout = result.stdout.strip()
            if not stdout:
                return {"ok": True}

            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return stdout

        except subprocess.TimeoutExpired:
            last_error = "超时"
            if attempt < max_retries - 1:
                delay = RETRY_DELAY_BASE ** (attempt + 1)
                logger.warning(f"lark-cli 超时，{delay}s 后重试 ({attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            logger.error("lark-cli 超时，已达最大重试次数")
            return None

        except Exception as e:
            last_error = str(e)
            logger.error(f"执行异常: {e}")
            if attempt < max_retries - 1:
                delay = RETRY_DELAY_BASE ** (attempt + 1)
                time.sleep(delay)
                continue
            return None

    logger.error(f"lark-cli 调用失败，已达最大重试次数: {last_error}")
    return None
