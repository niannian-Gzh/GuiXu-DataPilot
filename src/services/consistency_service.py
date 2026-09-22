import json
import pandas as pd
from display import format_table
from db import query_df


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


def _row_label(df, idx, row) -> str:
    """给一行数据一个"人能认得出"的标签。

    取第一列的值作标签——通常它是名称/主键，可读性最好。
    第一列为空则退化成"第 N 行"。
    """
    if len(df.columns) == 0:
        return f"第 {idx + 2} 行"
    first_col = df.columns[0]
    v = row.get(first_col)
    if v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "":
        return f"第 {idx + 2} 行"
    return str(v)


def check(ctx) -> dict:
    """单表一致性检查。

    规则是逐表的——每条规则先检查字段齐不齐，齐才跑。
    这样换一张表时，不适用的规则自动跳过，不会报"缺字段"的假错。
    """
    df = query_df(f"SELECT * FROM {ctx.real_table}")
    cols = set(df.columns)

    # 规则1：status_raw + 五个布尔字段
    bool_fields = ["is_pending", "is_submitted", "is_rejected",
                   "is_settled", "is_certified"]
    rule1_on = "status_raw" in cols and all(f in cols for f in bool_fields)

    # 规则2：certified_date < issued_date
    rule2_on = "certified_date" in cols and "issued_date" in cols

    # 规则3：reject_date < issued_date
    rule3_on = "reject_date" in cols and "issued_date" in cols

    # 规则4：resubmit_date < reject_date
    rule4_on = "resubmit_date" in cols and "reject_date" in cols

    applied = []
    if rule1_on:
        applied.append("状态文本与布尔字段一致")
    if rule2_on:
        applied.append("下证日期不早于下发日期")
    if rule3_on:
        applied.append("打回日期不早于下发日期")
    if rule4_on:
        applied.append("重提日期不早于打回日期")

    issues = []

    for idx, row in df.iterrows():
        label = _row_label(df, idx, row)

        if rule1_on:
            status = row["status_raw"] or ""
            expected = _recompute_flags(status)
            for field, exp_val in expected.items():
                actual = bool(row[field])
                if actual != exp_val:
                    issues.append({
                        "record": label,
                        "problem": (
                            f"{field}={actual}，但 status_raw='{status}' "
                            f"推导应为 {exp_val}"
                        ),
                    })

        if rule2_on:
            cd = _to_date_str(row.get("certified_date"))
            idt = _to_date_str(row.get("issued_date"))
            if cd and idt and cd < idt:
                issues.append({
                    "record": label,
                    "problem": f"下证日期({cd}) 早于 下发日期({idt})",
                })

        if rule3_on:
            rd = _to_date_str(row.get("reject_date"))
            idt = _to_date_str(row.get("issued_date"))
            if rd and idt and rd < idt:
                issues.append({
                    "record": label,
                    "problem": f"打回日期({rd}) 早于 下发日期({idt})",
                })

        if rule4_on:
            rsd = _to_date_str(row.get("resubmit_date"))
            rd = _to_date_str(row.get("reject_date"))
            if rsd and rd and rsd < rd:
                issues.append({
                    "record": label,
                    "problem": f"重提日期({rsd}) 早于 打回日期({rd})",
                })

    return {
        "total_scanned": len(df),
        "issue_count": len(issues),
        "issues": issues,
        "applied_rules": applied,
    }


def format_result(result: dict) -> str:
    """单表检查结果的展示。"""
    if result["issue_count"] == 0:
        if not result.get("applied_rules"):
            return (
                f"一致性检查完成：扫描 {result['total_scanned']} 条记录，"
                f"该表暂无适用的检查规则。"
            )
        return (
            f"一致性检查完成：扫描 {result['total_scanned']} 条记录，未发现问题。"
        )

    lines = [
        f"一致性检查完成：扫描 {result['total_scanned']} 条记录，"
        f"发现 **{result['issue_count']}** 个问题。\n"
    ]

    shown = result["issues"][:20]
    rows = [{"记录": i["record"], "问题": i["problem"]} for i in shown]
    lines.append(format_table(rows))

    if result["issue_count"] > 20:
        lines.append(f"\n（共 {result['issue_count']} 个问题，此处仅显示前 20 个）")

    return "\n".join(lines)


def run(ctx) -> str:
    """单表检查入口。"""
    result = check(ctx)
    return json.dumps(
        {
            "answer": format_result(result),
            "issue_count": result["issue_count"],
            "total_scanned": result["total_scanned"],
        },
        ensure_ascii=False,
    )


def run_all(base_ctx) -> str:
    """全库检查入口——遍历 schema_meta 里所有表，逐表跑各自适用的规则。"""
    from schema_store import get_all_tables_schema

    tables = get_all_tables_schema()
    if not tables:
        return json.dumps(
            {"answer": "数据字典里没有任何表。"},
            ensure_ascii=False,
        )

    results = []
    for t in tables:
        ctx = base_ctx.for_table(t["name"])
        r = check(ctx)
        r["table"] = t["name"]
        r["table_label"] = t["label"] or t["name"]
        results.append(r)

    total_issues = sum(r["issue_count"] for r in results)

    # 组装展示
    if total_issues == 0:
        answer = (
            f"一致性检查完成：检查了 {len(results)} 张表，未发现问题。"
        )
    else:
        lines = [
            f"一致性检查完成：检查了 {len(results)} 张表，"
            f"发现 **{total_issues}** 个问题。\n"
        ]
        for r in results:
            if r["issue_count"] == 0:
                continue
            lines.append(f"### {r['table_label']}（{r['issue_count']} 个问题）\n")
            shown = r["issues"][:20]
            rows = [{"记录": i["record"], "问题": i["problem"]} for i in shown]
            lines.append(format_table(rows))
            if r["issue_count"] > 20:
                lines.append(
                    f"（共 {r['issue_count']} 个，此处仅显示前 20 个）"
                )
            lines.append("")
        answer = "\n".join(lines)

    return json.dumps(
        {
            "answer": answer,
            "tables": [
                {"table": r["table"], "issue_count": r["issue_count"]}
                for r in results
            ],
        },
        ensure_ascii=False,
    )