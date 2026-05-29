#!/bin/bash
# 飞书项目部署脚本
#
# 用法:
#   bash deploy.sh              # 部署所有模块
#   bash deploy.sh expense      # 只部署费用报销模块
#   bash deploy.sh selection-erp # 只部署选品ERP模块

set -e

MODULE="${1:-all}"

echo "=========================================="
echo "飞书项目部署"
echo "模块: $MODULE"
echo "=========================================="

# 检查 Python3
if ! command -v python3 &> /dev/null; then
    echo "错误: 未找到 python3"
    exit 1
fi
echo "✓ Python3: $(python3 --version)"

# 检查 lark-cli
if ! command -v lark-cli &> /dev/null; then
    echo "lark-cli 未安装，正在安装..."
    if ! command -v npm &> /dev/null; then
        echo "安装 Node.js..."
        curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
        apt-get install -y nodejs
    fi
    npm install -g @larksuite/cli
fi
echo "✓ lark-cli: $(lark-cli --version 2>/dev/null || echo '已安装')"

# 检查 .env 文件
if [ ! -f ".env" ]; then
    echo "创建 .env 文件..."
    cp .env.example .env
    echo "请编辑 .env 文件配置相关参数后重新运行"
    exit 0
fi

echo "=========================================="
echo "部署完成"
echo ""

if [ "$MODULE" = "all" ] || [ "$MODULE" = "expense" ]; then
    echo "费用报销模块: bash run.sh expense"
fi
if [ "$MODULE" = "all" ] || [ "$MODULE" = "selection-erp" ]; then
    echo "选品ERP模块:  bash run.sh selection-erp"
fi
echo "=========================================="
