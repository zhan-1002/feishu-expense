#!/bin/bash
# 费用报销扫描引擎部署脚本

set -e

echo "=========================================="
echo "费用报销扫描引擎部署"
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
    echo "请编辑 .env 文件配置相关参数"
fi

echo "=========================================="
echo "部署完成"
echo "=========================================="
