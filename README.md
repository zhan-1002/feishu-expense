# 飞书多维表格自动化引擎

多模块飞书多维表格自动化项目。每个模块独立运行，通过 `common/` 共享公共库。

## 模块

| 模块 | 目录 | 用途 |
|------|------|------|
| expense | `expense/` | 费用报销：待提交 → 待审批 → 已通过/已拒绝 |
| selection-erp | `selection-erp/` | 选品ERP：派发 → 调研 → 初审 → 二优 → 终审 → 采购/结束/退回 |

## 架构

```
feishu-expense/
├── common/                     ← 公共库
│   └── feishu_api.py           ← lark-cli 调用封装（所有模块共享）
├── expense/                    ← 费用报销模块
│   ├── shared/                 ← 模块专用配置 & CRUD
│   └── scan_worker.py
├── selection-erp/              ← 选品ERP模块
│   ├── shared/                 ← 模块专用配置 & CRUD & 卡片
│   ├── scan_worker.py          ← 8阶段状态机扫描引擎
│   └── notify_worker.py        ← 通知队列发送
├── deploy.sh                   ← 一键部署
├── run.sh                      ← 启动脚本
├── .env.example                ← 环境变量模板
└── requirements.txt
```

## 环境要求

- **操作系统**: Linux (Ubuntu 20.04+)
- **Python**: 3.9+
- **Node.js**: 20+（lark-cli 依赖）
- **lark-cli**: 飞书 CLI 工具

## 一键部署

```bash
cd /opt/feishu-expense
bash deploy.sh                # 部署所有模块
bash deploy.sh expense        # 只部署费用报销
bash deploy.sh selection-erp  # 只部署选品ERP
```

## 启动服务

```bash
bash run.sh                   # 列出可用模块
bash run.sh expense           # 启动费用报销
bash run.sh selection-erp     # 启动选品ERP
bash run.sh all               # 启动全部
```

## 管理命令

```bash
# 查看日志
tail -f expense.log
tail -f selection-erp.log

# 停止服务
kill $(cat expense.pid)
kill $(cat selection-erp.pid)

# 单次扫描（调试用）
cd expense && python3 scan_worker.py
cd selection-erp && python3 scan_worker.py

# 手动发送通知（选品ERP）
cd selection-erp && python3 notify_worker.py
```

## 添加新模块

按以下模板创建：

```
新模块名/
├── shared/
│   ├── __init__.py
│   ├── config.py        # 模块专用配置
│   └── bitable_ops.py   # 模块专用 CRUD（从 common.feishu_api 导入 run_cli）
└── scan_worker.py       # 扫描入口
```

## 环境变量 (.env)

```bash
# lark-cli 配置
FEISHU_BASE_TOKEN=         # Base Token（必需）
FEISHU_CLI_PROFILE=        # lark-cli profile
FEISHU_APP_SECRET=         # 应用密钥（可选）

# 费用报销
EXPENSE_TABLE_ID=          # 报销单表 ID

# 选品ERP
NOTIFY_GROUP_CHAT_ID=      # 通知群 chat_id
MANAGER_OPEN_IDS=          # 主管 open_id 列表（逗号分隔）
```
