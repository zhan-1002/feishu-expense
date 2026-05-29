#!/usr/bin/env python3
"""创建实习工时模块的多维表格

创建两个表：
1. 周出勤记录表
2. 月度工时统计表
"""

import json
import subprocess
import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from internship.shared.config import BASE_TOKEN, CLI_PROFILE

def run_cli(*args):
    """运行 lark-cli 命令"""
    cmd = ["lark-cli"]
    if CLI_PROFILE:
        cmd.extend(["--profile", CLI_PROFILE])
    cmd.extend(args)

    print(f"执行: {' '.join(cmd[:5])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"错误: {result.stderr}")
        return None

    if result.stdout.strip():
        return json.loads(result.stdout)
    return {"ok": True}


def create_weekly_attendance_table():
    """创建周出勤记录表"""
    print("\n" + "=" * 60)
    print("创建周出勤记录表")
    print("=" * 60)

    # 字段定义
    fields = [
        {"name": "员工", "type": 11, "property": {"multiple": False}},  # 人员类型
        {"name": "周开始日期", "type": 1},  # 日期
        {"name": "周结束日期", "type": 1},  # 日期
        {"name": "周一", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周二", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周三", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周四", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周五", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周六", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "周日", "type": 3, "property": {"options": [
            {"name": "全天", "color": 0},
            {"name": "上午", "color": 1},
            {"name": "下午", "color": 2},
            {"name": "无", "color": 3},
        ]}},
        {"name": "出勤状态", "type": 3, "property": {"options": [
            {"name": "待填写", "color": 0},
            {"name": "待确认", "color": 1},
            {"name": "已确认", "color": 2},
        ]}},
        {"name": "填写时间", "type": 1},  # 日期
        {"name": "确认时间", "type": 1},  # 日期
        {"name": "所属月份", "type": 1},  # 文本，格式 YYYY-MM
    ]

    # 字段类型说明：
    # text = 文本, number = 数字, select = 单选, datetime = 日期, user = 人员

    fields_corrected = [
        {"name": "员工", "type": "user", "property": {"multiple": False}},
        {"name": "周开始日期", "type": "datetime"},
        {"name": "周结束日期", "type": "datetime"},
        {"name": "周一", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周二", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周三", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周四", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周五", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周六", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "周日", "type": "select", "property": {"options": [
            {"name": "全天"}, {"name": "上午"}, {"name": "下午"}, {"name": "无"}
        ]}},
        {"name": "出勤状态", "type": "select", "property": {"options": [
            {"name": "待填写"}, {"name": "待确认"}, {"name": "已确认"}
        ]}},
        {"name": "填写时间", "type": "datetime"},
        {"name": "确认时间", "type": "datetime"},
        {"name": "所属月份", "type": "text"},
    ]

    result = run_cli(
        "base", "+table-create",
        "--base-token", BASE_TOKEN,
        "--name", "周出勤记录",
        "--fields", json.dumps(fields_corrected, ensure_ascii=False)
    )

    if result and result.get("ok"):
        table_id = result.get("data", {}).get("table_id", "")
        print(f"✓ 周出勤记录表创建成功: {table_id}")
        return table_id
    else:
        print("✗ 创建失败")
        return None


def create_monthly_summary_table():
    """创建月度工时统计表"""
    print("\n" + "=" * 60)
    print("创建月度工时统计表")
    print("=" * 60)

    fields = [
        {"name": "员工", "type": "user", "property": {"multiple": False}},
        {"name": "统计月份", "type": "text"},
        {"name": "应出勤天数", "type": "number"},
        {"name": "实际出勤天数", "type": "number"},
        {"name": "出勤率", "type": "number"},
        {"name": "统计状态", "type": "select", "property": {"options": [
            {"name": "待提交"},
            {"name": "待审批"},
            {"name": "已通过"},
            {"name": "已退回"}
        ]}},
        {"name": "提交时间", "type": "datetime"},
        {"name": "审批结果", "type": "select", "property": {"options": [
            {"name": "待审批"},
            {"name": "通过"},
            {"name": "退回"}
        ]}},
        {"name": "审批时间", "type": "datetime"},
        {"name": "审批备注", "type": "text"},
    ]

    result = run_cli(
        "base", "+table-create",
        "--base-token", BASE_TOKEN,
        "--name", "月度工时统计",
        "--fields", json.dumps(fields, ensure_ascii=False)
    )

    if result and result.get("ok"):
        table_id = result.get("data", {}).get("table_id", "")
        print(f"✓ 月度工时统计表创建成功: {table_id}")
        return table_id
    else:
        print("✗ 创建失败")
        return None


def main():
    print("=" * 60)
    print("实习工时模块 - 表格创建脚本")
    print(f"BASE_TOKEN: {BASE_TOKEN}")
    print("=" * 60)

    # 创建周出勤记录表
    weekly_table_id = create_weekly_attendance_table()

    # 创建月度工时统计表
    monthly_table_id = create_monthly_summary_table()

    # 输出结果
    print("\n" + "=" * 60)
    print("创建完成，请将以下配置添加到 .env 文件：")
    print("=" * 60)
    if weekly_table_id:
        print(f"WEEKLY_ATTENDANCE_TABLE_ID={weekly_table_id}")
    if monthly_table_id:
        print(f"MONTHLY_SUMMARY_TABLE_ID={monthly_table_id}")


if __name__ == "__main__":
    main()
