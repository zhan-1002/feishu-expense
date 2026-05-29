#!/usr/bin/env python3
"""为实习工时表格添加字段"""

import json
import subprocess
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from internship.shared.config import BASE_TOKEN, CLI_PROFILE

WEEKLY_TABLE_ID = "tblJZkXui6OYQH0Y"
MONTHLY_TABLE_ID = "tblwkVKbUNHG0Dkz"


def run_cli(*args):
    """运行 lark-cli 命令"""
    cmd = ["lark-cli"]
    if CLI_PROFILE:
        cmd.extend(["--profile", CLI_PROFILE])
    cmd.extend(args)

    print(f"执行: {' '.join(cmd[:6])}...")
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"错误: {result.stderr}")
        return None

    if result.stdout.strip():
        try:
            return json.loads(result.stdout)
        except:
            return {"ok": True, "raw": result.stdout}
    return {"ok": True}


def create_field(table_id, field_def):
    """创建单个字段"""
    result = run_cli(
        "base", "+field-create",
        "--base-token", BASE_TOKEN,
        "--table-id", table_id,
        "--json", json.dumps(field_def, ensure_ascii=False)
    )
    if result and result.get("ok"):
        field_id = result.get("data", {}).get("field", {}).get("id", "")
        print(f"  ✓ {field_def['name']}: {field_id}")
        return field_id
    else:
        print(f"  ✗ {field_def['name']}: 失败")
        return None


def create_weekly_fields():
    """创建周出勤记录表字段"""
    print("\n创建周出勤记录表字段...")

    # 简化字段定义，不带 property
    fields = [
        {"name": "员工", "type": "user"},
        {"name": "周一", "type": "select"},
        {"name": "周二", "type": "select"},
        {"name": "周三", "type": "select"},
        {"name": "周四", "type": "select"},
        {"name": "周五", "type": "select"},
        {"name": "周六", "type": "select"},
        {"name": "周日", "type": "select"},
        {"name": "出勤状态", "type": "select"},
    ]

    for field in fields:
        create_field(WEEKLY_TABLE_ID, field)


def create_monthly_fields():
    """创建月度工时统计表字段"""
    print("\n创建月度工时统计表字段...")

    fields = [
        {"name": "员工", "type": "user"},
        {"name": "统计状态", "type": "select"},
        {"name": "审批结果", "type": "select"},
    ]

    for field in fields:
        create_field(MONTHLY_TABLE_ID, field)


def main():
    print("=" * 60)
    print("实习工时模块 - 字段创建脚本")
    print("=" * 60)

    create_weekly_fields()
    create_monthly_fields()

    print("\n完成！")


if __name__ == "__main__":
    main()