"""lark-cli 调用封装"""
import json
import logging
import subprocess
from typing import Any, Dict, Optional

from .config import LARK_CLI, CLI_PROFILE

logger = logging.getLogger(__name__)


def run_cli(*args: str) -> Optional[Dict[str, Any]]:
    """调用 lark-cli，返回解析后的 JSON 结果"""
    cmd = [LARK_CLI]
    if CLI_PROFILE:
        cmd.extend(["--profile", CLI_PROFILE])
    cmd.extend(args)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.error(f"lark-cli 错误: {result.stderr}")
            return None

        stdout = result.stdout.strip()
        if not stdout:
            return {"ok": True}

        return json.loads(stdout)

    except subprocess.TimeoutExpired:
        logger.error("lark-cli 超时")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON 解析失败: {e}")
        return None
    except Exception as e:
        logger.error(f"执行异常: {e}")
        return None