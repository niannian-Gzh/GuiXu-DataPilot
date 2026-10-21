"""文档 → 纯文本。

只做一件事：把格式差异吃掉，输出干净的文字。分块和向量都不在这里。

三种格式各有各的坑：

- **PDF 只是"能不能提取文字"**：扫描件没有文字层，提取出来是空的。
  不装作能处理——明确报错，别让用户以为入库成功、检索却永远搜不到
- **docx 的正文不只在段落里**：表格里的字也是内容，只读 paragraphs 会丢
- **txt/md 在中文 Windows 上经常是 GBK**：UTF-8 读失败就换编码，
  不是所有用户都拿 VS Code 存文件
"""

from __future__ import annotations

import re
from pathlib import Path

from rag import RagError


def parse(path: Path, kind: str, llm=None, max_pages: int = 30) -> str:
    if kind == "text":
        text = _read_text(path)
    elif kind == "docx":
        text = _read_docx(path)
    elif kind == "pdf":
        text = _read_pdf(path)
        text = _clean(text)
        if not text.strip():
            # 没有文字层：交给多模态模型读图。没有视觉能力就明确报错，
            # 不装作入库成功
            text = _read_scanned_pdf(path, llm, max_pages)
    else:
        raise RagError(f"不认识的文档类型：{kind}")

    text = _clean(text)
    if not text.strip():
        raise RagError("文档里没有可提取的文字")
    return text


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    # 最后兜底：宁可留几个问号，也别拒绝一份其余部分能读的文档
    return raw.decode("utf-8", errors="replace")


def _read_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n\n".join(parts)


def _read_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    if reader.is_encrypted:
        raise RagError("这份 PDF 加密了，无法提取文字")
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception as e:
            raise RagError(f"PDF 第 {len(pages) + 1} 页解析失败：{e}") from e
    return "\n\n".join(p for p in pages if p.strip())


def _read_scanned_pdf(path: Path, llm, max_pages: int) -> str:
    """扫描件：页面渲染成图片，交给多模态模型抽文字。

    前提是模型认图片。不认就报清楚——「换个支持视觉的模型」比
    「入库成功但永远搜不到」有用得多。
    """
    caps = getattr(llm, "capabilities", {}) or {}
    if llm is None or not caps.get("vision"):
        raise RagError(
            "这份 PDF 没有文字层，是扫描件。"
            "您当前使用的模型没有图片识别能力，无法识别扫描件PDF。"
            "请在设置里换一个支持图片输入的模型配置。"
        )

    import pymupdf

    doc = pymupdf.open(str(path))
    try:
        total = len(doc)
        if total > max_pages:
            raise RagError(
                f"扫描件共 {total} 页，超过 {max_pages} 页上限。"
                "请拆分后再上传，或到设置里调高上限"
            )

        parts = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=150)
            text = llm.describe_images(
                [pix.tobytes("png")],
                "请提取这一页里的全部文字，按原文顺序输出。"
                "只输出文字本身，不要总结、不要解释、不要加标题。",
            )
            text = (text or "").strip()
            if text:
                parts.append(f"[第 {i + 1} 页]\n{text}")
    finally:
        doc.close()

    if not parts:
        raise RagError("模型没有从这份扫描件里识别出文字")
    return "\n\n".join(parts)


def _clean(text: str) -> str:
    """规范换行和空行——分块靠空行切段，这里先把格式统一。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)       # 行尾空白
    text = re.sub(r"\n{3,}", "\n\n", text)       # 连续空行压成一段分隔
    return text.strip()
