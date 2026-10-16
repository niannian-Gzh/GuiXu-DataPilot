def format_table(rows: list[dict]) -> str:
    """一组 dict → markdown 表格。dict 的 key 就是表头。"""
    if not rows:
        return "（无记录）"

    columns = list(rows[0].keys())
    lines = [
        "| " + " | ".join(columns) + " |",
        "|" + "|".join(["---"] * len(columns)) + "|",
    ]
    for row in rows:
        cells = ["" if row.get(c) is None else str(row.get(c)) for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
