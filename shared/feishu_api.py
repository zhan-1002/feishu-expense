"""lark-cli 调用封装"""
import json
import logging
import subprocess
import time
from typing import Any, Dict, Optional

from .config import LARK_CLI, CLI_PROFILE

logger = logging.getLogger(__name__)

# 默认超时时间（秒）
DEFAULT_TIMEOUT_SECONDS = 60

# 重试配置
MAX_RETRIES = 3
RETRY_DELAY_BASE = 2  # 指数退避基础延迟（秒）


def run_cli(*args: str, timeout: Optional[int] = None, max_retries: int = MAX_RETRIES) -> Optional[Dict[str, Any]]:
    """调用 lark-cli，返回解析后的 JSON 结果

    Args:
        *args: lark-cli 命令参数
        timeout: 超时时间（秒），默认 60
        max_retries: 最大重试次数，默认 3

    Returns:
        解析后的 JSON 结果，失败返回 None
    """
    timeout = timeout or DEFAULT_TIMEOUT_SECONDS
    cmd = [LARK_CLI]
    if CLI_PROFILE:
        cmd.extend(["--profile", CLI_PROFILE])
    cmd.extend(args)

    last_error: Optional[str] = None

    for attempt in range(max_retries):
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode != 0:
                last_error = result.stderr
                # 非网络错误，不重试
                if "timeout" not in result.stderr.lower() and "connection" not in result.stderr.lower():
                    logger.error(f"lark-cli 错误: {result.stderr}")
                    return None
                # 网络错误，尝试重试
                if attempt < max_retries - 1:
                    delay = RETRY_DELAY_BASE ** (attempt + 1)
                    logger.warning(f"lark-cli 调用失败，{delay}s 后重试 (attempt {attempt + 1}/{max_retries})")
                    time.sleep(delay)
                    continue
                logger.error(f"lark-cli 错误: {result.stderr}")
                return None

            stdout = result.stdout.strip()
            if not stdout:
                return {"ok": True}

            return json.loads(stdout)

        except subprocess.TimeoutExpired:
            last_error = "超时"
            if attempt < max_retries - 1:
                delay = RETRY_DELAY_BASE ** (attempt + 1)
                logger.warning(f"lark-cli 超时，{delay}s 后重试 (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            logger.error("lark-cli 超时，已达最大重试次数")
            return None

        except json.JSONDecodeError as e:
            logger.error(f"JSON 解析失败: {e}")
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