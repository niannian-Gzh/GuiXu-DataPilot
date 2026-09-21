import json
import pandas as pd
from db import query_df
from display import format_table


def _recompute_flags(status_raw: str) -> dict:
    return {
        "is_pending": "待提交" in status_raw,
        "is_submitted": "已提交" in status_raw,
        "is_rejected": "已打回" in status_raw,
        "is_settled": "已结算" in status_raw,
        "is_certified": "已下证" in status_raw,
    }


def _to_date_str(v):
    if v is None or pd.isna(v):
        return None
    return str(v)[:10]


def check(ctx) -> dict:
    df = query_df(f"SELECT * FROM {ctx.real_table}")

    issues = []

    for _, row in df.iterrows():
        name = row["project_name"]
        status = row["status_raw"] or ""

        # 规则1：status_raw 和布尔字段不匹配
        expected = _recompute_flags(status)
        for field, exp_val in expected.items():
            actual = bool(row[field])
            if actual != exp_val:
                issues.append({
                    "project_name": name,
                    "problem": (
                        f"{field}={actual}，但 status_raw='{status}' "
                        f"推导应为 {exp_val}"
                    ),
                })

        # 规则2：certified_date < issued_date
        cd = _to_date_str(row.get("certified_date"))
        idt = _to_date_str(row.get("issued_date"))
        if cd and idt and cd < idt:
            issues.append({
                "project_name": name,
                "problem": f"下证日期({cd}) 早于 下发日期({idt})",
            })

        # 规则3：reject_date < issued_date
        rd = _to_date_str(row.get("reject_date"))
        if rd and idt and rd < idt:
            issues.append({
                "project_name": name,
                "problem": f"打回日期({rd}) 早于 下发日期({idt})",
            })

        # 规则4：resubmit_date < reject_date
        rsd = _to_date_str(row.get("resubmit_date"))
        if rsd and rd and rsd < rd:
            issues.append({
                "project_name": name,
                "problem": f"重提日期({rsd}) 早于 打回日期({rd})",
            })

    return {
        "total_scanned": len(df),
        "issue_count": len(issues),
        "issues": issues,
    }


def format_result(result: dict) -> str:
    if result["issue_count"] == 0:
        return (
            f"一致性检查完成：扫描 {result['total_scanned']} 条记录，未发现问题。"
        )

    lines = [
        f"一致性检查完成：扫描 {result['total_scanned']} 条记录，"
        f"发现 **{result['issue_count']}** 个问题。\n"
    ]

    shown = result["issues"][:20]
    rows = [
        {"项目名称": i["project_name"], "问题": i["problem"]}
        for i in shown
    ]
    lines.append(format_table(rows))

    if result["issue_count"] > 20:
        lines.append(f"\n（共 {result['issue_count']} 个问题，此处仅显示前 20 个）")

    return "\n".join(lines)


def run(ctx) -> str:
    result = check(ctx)
    return json.dumps(
        {
            "answer": format_result(result),
            "issue_count": result["issue_count"],
            "total_scanned": result["total_scanned"],
        },
        ensure_ascii=False,
    )