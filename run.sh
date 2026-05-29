#!/bin/bash
# 启动扫描引擎
#
# 用法:
#   bash run.sh                  # 列出可用模块
#   bash run.sh expense          # 启动费用报销模块
#   bash run.sh selection-erp    # 启动选品ERP模块
#   bash run.sh all              # 启动所有模块

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODULE="${1:-}"

if [ -z "$MODULE" ]; then
    echo "可用模块:"
    echo "  expense        费用报销扫描引擎"
    echo "  selection-erp  选品ERP扫描引擎 + 通知发送"
    echo "  all            启动所有模块"
    echo ""
    echo "用法: bash run.sh <模块名>"
    exit 0
fi

# 检查 lark-cli
if ! command -v lark-cli &> /dev/null; then
    echo "错误: 未找到 lark-cli，请先运行 deploy.sh"
    exit 1
fi

_start_module() {
    local NAME="$1"
    local SCRIPT="$2"
    local PID_FILE="${NAME}.pid"
    local LOG_FILE="${NAME}.log"

    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            echo "[$NAME] 已在运行 (PID: $OLD_PID)"
            return
        fi
    fi

    echo "[$NAME] 启动..."
    nohup python3 "$SCRIPT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "[$NAME] 已启动 (PID: $(cat $PID_FILE), 日志: $LOG_FILE)"
}

if [ "$MODULE" = "all" ] || [ "$MODULE" = "expense" ]; then
    _start_module "expense" "expense/scan_worker.py"
fi

if [ "$MODULE" = "all" ] || [ "$MODULE" = "selection-erp" ]; then
    _start_module "selection-erp" "selection-erp/scan_worker.py"
fi

echo ""
echo "管理命令:"
echo "  tail -f <模块名>.log    查看日志"
echo "  kill \$(cat <模块名>.pid)  停止服务"
