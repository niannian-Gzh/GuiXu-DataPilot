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
        cells = [str(row.get(c, "") or "") for c in columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def format_list(items: list[str]) -> str:
    """列表 → markdown 无序列表。"""
    return "\n".join(f"- {item}" for item in items)


def format_quote(text: str) -> str:
    """文本 → markdown 引用块。"""
    return "\n".join(f"> {line}" for line in text.split("\n"))
