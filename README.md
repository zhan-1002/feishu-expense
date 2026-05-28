# 费用报销自动化引擎

飞书多维表格自动化扫描引擎。每 5 分钟轮询报销单，自动推进报销流程状态流转（待提交→待审批→已通过/已拒绝）。

## 架构

```
scan_worker.py  ──→  费用报销单表
     │
     └── 自动推进状态流转
```

### 状态流转规则

```
待提交 → 待审批 → 已通过
                 └→ 已拒绝
```

## 环境要求

- **操作系统**: Linux (Ubuntu 20.04+)
- **Python**: 3.9+
- **lark-cli**: 飞书 CLI 工具

## 一键部署

```bash
cd /opt/feishu-expense
bash deploy.sh
```

## 启动服务

```bash
bash run.sh
```

## 管理命令

```bash
# 查看实时日志
tail -f scan.log

# 停止服务
kill $(cat scan_worker.pid)

# 单次扫描（调试用）
python3 -c "from scan_worker import scan_cycle; scan_cycle()"
```

## 文件说明

```
feishu-expense/
├── deploy.sh            # 一键部署脚本
├── run.sh               # 启动脚本
├── scan_worker.py       # 扫描引擎（主进程）
├── requirements.txt     # Python 依赖
├── .env.example         # 环境变量模板
├── .env                 # 实际环境变量
├── shared/
│   ├── __init__.py
│   ├── config.py        # Base/表/字段配置
│   ├── bitable_ops.py   # 多维表格 CRUD
│   └── feishu_api.py    # lark-cli 调用封装
├── scan.log             # 运行日志
└── scan_worker.pid      # 进程 PID
```

## 视图和角色

### 视图
- **全部报销单**: 管理员查看所有记录
- **我的报销**: 申请人查看自己的报销单
- **待我审批**: 审批人查看待审批的报销单
- **已通过**: 已通过的报销单
- **已拒绝**: 已拒绝的报销单

### 角色
- **申请人**: 只能查看和编辑自己的报销单
- **审批人**: 可查看待审批的报销单，审批分配给自己的记录
