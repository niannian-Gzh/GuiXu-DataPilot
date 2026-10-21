"""分块：按段落聚合，超长段落按句子切。

**不按固定字数硬切。** 500 字一刀切下去，句子中间断开，检索命中后
模型拿到的第一段是半句话——那比不命中更糟，因为它看起来是完整证据。

做法：先把文档切成"段落 / 句子"这类天然单位，再按预算往块里装。
块之间保留 `overlap` 个字符，让跨块的上下文有一条缝能对上。
"""

from __future__ import annotations

import re

# 句子结束符。中文标点为主，英文标点兼容——文档里混着英文很常见
_SENTENCE_END = re.compile(r"(?<=[。！？!?；;])\s*")


def split(text: str, size: int, overlap: int) -> list[str]:
    """返回块列表。`size` / `overlap` 都是字符数。"""
    size = max(int(size), 100)
    overlap = max(0, min(int(overlap), size - 1))

    units = _units(text)
    if not units:
        return []

    chunks: list[str] = []
    current = ""

    for unit in units:
        piece = unit if not current else "\n" + unit
        if len(current) + len(piece) <= size:
            current += piece
            continue

        if current:
            chunks.append(current.strip())

        # 下一块从上一块的尾部借 overlap 个字符。切在句子里也没关系——
        # 它只作为上下文冗余，真正的证据在前一块里已经完整了
        tail = current[-overlap:] if overlap else ""
        current = (tail + "\n" + unit).strip() if tail else unit

        # 单个单位就超过预算（比如一整段没有句号）：按 size 硬切，
        # 但每片都带上一片尾巴，至少不让边界完全裸奔
        while len(current) > size:
            chunks.append(current[:size].strip())
            current = (current[size - overlap:]).strip()

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


def _units(text: str) -> list[str]:
    """段落 → 超长段落拆成句子。短段落本身就是一个单位。"""
    out = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= 600:
            out.append(para)
            continue
        for sent in _SENTENCE_END.split(para):
            sent = sent.strip()
            if sent:
                out.append(sent)
    return out
