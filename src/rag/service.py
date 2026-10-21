"""文档库的动作：入库、列表、删除、恢复、清理、重建索引、检索。

**不经过模型的上传/删除** 和 **模型发起的检索** 都收在这里，
入口不同，执行端只有一份——和恢复页复用了删除/恢复的执行端是同一条账。

删除是软删：文档和切片都留着，检索与列表过滤掉；回收站可恢复；
保留期到了才物理删（切片 + 原文件），并留审计。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from audit import record
from config import setting
from rag import DOC_DIR, RagError, SUPPORTED, chunker, embedding, index, parser, store
from rag import rerank
from runner import connect, transaction


def ingest(src: Path, original_name: str, keep_source: bool = False, llm=None) -> dict:
    """一份文档 → 原文落盘 + 切片入库 + 向量进索引。

    `keep_source=True` 用于「把产物收进文档库」：文件要同时留在产物栏，
    所以复制而不是搬走。上传的临时文件则应该搬走（别留垃圾）。

    `llm` 只给扫描件 PDF 用：没有文字层时，页面转图片交给多模态模型。
    """
    name = Path(original_name).name.strip()[:200] or "未命名文档"
    suffix = Path(name).suffix.lower()
    kind = SUPPORTED.get(suffix)
    if not kind:
        raise RagError(
            f"不支持的文档格式：{suffix or '（没有扩展名）'}。"
            "可用：PDF / Word(.docx) / txt / md"
        )

    src = Path(src)
    data = src.read_bytes()
    if not data:
        raise RagError("文件是空的")
    sha = hashlib.sha256(data).hexdigest()

    con = connect()
    try:
        dup = store.find_by_sha(con, sha)
    finally:
        con.close()
    if dup:
        if dup[2]:
            raise RagError(f"这份文档在回收站里：《{dup[1]}》，先到回收站恢复它")
        raise RagError(f"这份文档已经在库里了：《{dup[1]}》")

    # 解析和向量都在事务外：它们慢，而且失败时不该占着写锁
    text = parser.parse(
        src, kind, llm=llm, max_pages=int(setting("rag.vision_max_pages")),
    )
    chunks = chunker.split(
        text, setting("rag.chunk_size"), setting("rag.chunk_overlap"),
    )
    if not chunks:
        raise RagError("分块后没有内容")
    vectors = embedding.encode(chunks)

    DOC_DIR.mkdir(parents=True, exist_ok=True)
    stored = f"{uuid.uuid4().hex}{suffix}"
    target = DOC_DIR / stored
    if keep_source:
        shutil.copy2(src, target)
    else:
        shutil.move(str(src), target)

    try:
        with transaction() as tx:
            doc_id = store.add(
                tx, name=name, path=stored, kind=kind, size=len(data),
                sha256=sha, chunks=chunks, vectors=vectors,
            )
            # 文档操作也是写操作，同样要有凭据——和切片在同一个事务里
            record(tx, "doc_upload", {
                "table": "_gx_doc", "doc_id": doc_id, "name": name,
                "kind": kind, "chunks": len(chunks),
            })
    except Exception:
        # 元信息和切片要么一起成、要么一起不成；失败时别把孤儿文件留下
        target.unlink(missing_ok=True)
        raise

    index.invalidate()
    return {
        "id": doc_id, "name": name, "kind": kind,
        "size": len(data), "chunks": len(chunks),
    }


def list_documents() -> dict:
    con = connect()
    try:
        docs = store.list_docs(con)
        deleted = store.list_docs(con, deleted=True)
        counts = store.counts(con)
    finally:
        con.close()

    days = int(setting("safety.retention_days"))
    now = datetime.now()
    for d in deleted:
        d["days_left"] = _days_left(d.get("deleted_at"), days, now)

    return {"documents": docs, "deleted": deleted, "counts": counts}


def preview_document(doc_id: int) -> dict:
    """看解析后的全文和分块。**不重新解析**——切片就是解析结果，
    已软删的文档不给看（回收站里恢复后再看）。"""
    con = connect()
    try:
        row = store.get_doc(con, doc_id)
        if not row or row[5]:
            raise RagError("文档不存在或已删除")
        chunks = store.chunks_of_doc(con, doc_id)
    finally:
        con.close()

    return {
        "id": row[0], "name": row[1], "kind": row[3], "size": row[4],
        "added_at": row[7],
        "text": "\n\n".join(c["text"] for c in chunks),
        "chunks": chunks,
    }


def delete(doc_id: int) -> dict:
    con = connect()
    try:
        row = store.get_doc(con, doc_id)
    finally:
        con.close()
    if not row:
        raise RagError(f"文档不存在：{doc_id}")
    if row[5]:
        raise RagError("文档已经在回收站里")

    with transaction() as tx:
        store.soft_delete(tx, doc_id)
        record(tx, "doc_delete", {
            "table": "_gx_doc", "doc_id": doc_id, "name": row[1],
        })

    index.invalidate()
    return {"id": doc_id, "name": row[1]}


def restore(doc_id: int) -> dict:
    con = connect()
    try:
        row = store.get_doc(con, doc_id)
    finally:
        con.close()
    if not row:
        raise RagError(f"文档不存在：{doc_id}")
    if not row[5]:
        raise RagError("文档没有被删除")

    with transaction() as tx:
        store.restore(tx, doc_id)
        record(tx, "doc_restore", {
            "table": "_gx_doc", "doc_id": doc_id, "name": row[1],
        })

    index.invalidate()
    return {"id": doc_id, "name": row[1]}


def purge_expired(days: int | None = None) -> int:
    """物理删除超过保留期的文档：切片、元信息、原文件一起走。"""
    days = int(days if days is not None else setting("safety.retention_days"))
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(
        sep=" ", timespec="seconds",
    )

    con = connect()
    try:
        rows = store.expired(con, cutoff)
    finally:
        con.close()

    for doc_id, name, path in rows:
        with transaction() as tx:
            store.purge(tx, doc_id)
            record(tx, "doc_purge", {
                "table": "_gx_doc", "doc_id": doc_id, "name": name,
                "retention_days": days,
            })
        (DOC_DIR / path).unlink(missing_ok=True)

    if rows:
        index.invalidate()
    return len(rows)


def rebuild() -> dict:
    started = time.time()
    n = index.rebuild()
    return {"chunks": n, "ms": int((time.time() - started) * 1000)}


def search(query: str, top_k: int | None = None) -> dict:
    query = (query or "").strip()
    if not query:
        raise RagError("检索词不能为空")

    k = int(top_k or setting("rag.top_k"))
    k = max(1, min(k, 20))

    con = connect()
    try:
        total = store.counts(con)["chunks"]
    finally:
        con.close()
    if total == 0:
        return {
            "query": query, "results": [], "row_count": 0, "empty": True,
            "message": "文档库还没有内容",
        }

    vector = embedding.encode([query])[0]
    # 多取一些：低分过滤和 rerank 都会让候选变少
    hits = index.search(vector, max(k * 3, k))

    con = connect()
    try:
        rows = store.chunks_by_ids(con, [cid for cid, _ in hits])
    finally:
        con.close()

    min_score = float(setting("rag.min_score"))
    results = []
    for chunk_id, score in hits:
        if score < min_score:
            continue
        row = rows.get(chunk_id)
        if not row:
            continue
        results.append({
            "chunk_id": chunk_id,
            "doc": row["doc"],
            "seq": row["seq"],
            "score": round(score, 4),
            "text": row["text"],
        })

    # 粗排是向量分；reranker 只做精排。没有权重时原样返回
    results = rerank.rerank(query, results, k)[:k]

    return {
        "query": query,
        "results": results,
        "row_count": len(results),
        # 和其它工具同一套语义：empty 是事实，不是失败
        "status": "empty" if not results else "ok",
        "empty": not results,
        "message": "" if results else "没有找到足够相关的内容",
    }


def search_json(query: str, top_k: int | None = None) -> str:
    """工具层的返回形状：和别的工具一样只看 `ok`。"""
    try:
        data = search(query, top_k)
        data["ok"] = True
    except RagError as e:
        data = {"ok": False, "error": str(e), "error_type": "invalid"}
    except Exception as e:
        data = {"ok": False, "error": str(e), "error_type": "unknown"}
    return json.dumps(data, ensure_ascii=False)


def counts() -> dict:
    con = connect()
    try:
        return store.counts(con)
    finally:
        con.close()


def status() -> dict:
    data = counts()
    data["model"] = embedding.available()
    data["reranker"] = rerank.available()
    return data


def _days_left(deleted_at, days: int, now: datetime):
    if not deleted_at:
        return None
    try:
        t = datetime.fromisoformat(str(deleted_at))
    except ValueError:
        return None
    return max(days - (now - t).days, 0)
