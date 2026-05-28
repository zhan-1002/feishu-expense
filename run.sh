#!/bin/bash
# 启动费用报销扫描引擎

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 lark-cli
if ! command -v lark-cli &> /dev/null; then
    echo "错误: 未找到 lark-cli，请先运行 deploy.sh"
    exit 1
fi

# 检查是否已运行
if [ -f "scan_worker.pid" ]; then
    OLD_PID=$(cat scan_worker.pid)
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "扫描引擎已在运行 (PID: $OLD_PID)"
        exit 1
    fi
fi

echo "启动费用报销扫描引擎..."
nohup python3 scan_worker.py > scan.log 2>&1 &
echo $! > scan_worker.pid

echo "已启动 (PID: $(cat scan_worker.pid))"
echo "日志文件: scan.log"
