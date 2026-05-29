#!/usr/bin/env python3
"""为 select 字段添加选项"""

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


def update_field_options(table_id, field_id, options):
    """更新 select 字段的选项"""
    field_def = {
        "type": "select",
        "multiple": False,
        "options": [{"name": opt} for opt in options]
    }

    result = run_cli(
        "base", "+field-update",
        "--base-token", BASE_TOKEN,
        "--table-id", table_id,
        "--field-id", field_id,
        "--json", json.dumps(field_def, ensure_ascii=False),
        "--yes"
    )

    if result and result.get("ok"):
        print(f"  ✓ 选项已添加: {options}")
        return True
    else:
        print(f"  ✗ 添加失败")
        return False


def main():
    print("=" * 60)
    print("添加 select 字段选项")
    print("=" * 60)

    # 周出勤记录表
    print("\n周出勤记录表:")
    attendance_options = ["全天", "上午", "下午", "无"]

    day_fields = {
        "fld5lZy4z4": "周一",
        "fldQP5H3FS": "周二",
        "fldBgEvG4z": "周三",
        "fldOqxpFnF": "周四",
        "fldkmJLJml": "周五",
        "fldmmKQKox": "周六",
        "fldP8WZ7aQ": "周日",
    }

    for field_id, name in day_fields.items():
        print(f"  {name}:")
        update_field_options(WEEKLY_TABLE_ID, field_id, attendance_options)

    print("\n  出勤状态:")
    update_field_options(WEEKLY_TABLE_ID, "fldrdoZXUQ", ["待填写", "待确认", "已确认"])

    # 月度工时统计表
    print("\n月度工时统计表:")
    print("\n  统计状态:")
    update_field_options(MONTHLY_TABLE_ID, "fldGAUdR8l", ["待提交", "待审批", "已通过", "已退回"])

    print("\n  审批结果:")
    update_field_options(MONTHLY_TABLE_ID, "fldjSP1C8C", ["待审批", "通过", "退回"])

    print("\n完成！")


if __name__ == "__main__":
    main()