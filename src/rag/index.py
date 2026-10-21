"""FAISS 索引：派生数据，随时可以从 SQLite 重建。

**只负责"哪几条最像"**，不存原文。返回的是 chunk id，原文回 SQLite 取。

索引是进程内的，不落盘：
- 落盘就要保证"库变了索引也变"，而跨存储没有事务
- 几千条向量重建是毫秒级，启动时建一次不亏
- 任何写操作调 `invalidate()`，下一次检索前自动重建

换索引类型时只动这一个文件——切片、向量、检索接口都不变。
"""

from __future__ import annotations

import threading

import numpy as np

from rag import DIM

_lock = threading.Lock()
_index = None


def invalidate() -> None:
    """数据变了。下一次检索前重建。"""
    global _index
    with _lock:
        _index = None


def _build():
    import faiss

    from runner import connect

    con = connect()
    try:
        # 软删的文档不进索引。FAISS 是派生的，重建时按真源的可见状态来
        rows = con.execute(
            "SELECT c.id, c.embedding FROM _gx_chunk c "
            "JOIN _gx_doc d ON d.id = c.doc_id WHERE d.is_deleted = 0"
        ).fetchall()
    finally:
        con.close()

    index = faiss.IndexIDMap2(faiss.IndexFlatIP(DIM))
    if rows:
        vectors = np.vstack([
            np.frombuffer(blob, dtype=np.float32) for _, blob in rows
        ])
        ids = np.array([cid for cid, _ in rows], dtype=np.int64)
        index.add_with_ids(vectors, ids)
    return index


def rebuild() -> int:
    """主动重建，返回索引里的向量数。"""
    global _index
    with _lock:
        _index = _build()
        return int(_index.ntotal)


def search(vector: np.ndarray, k: int) -> list[tuple[int, float]]:
    """返回 [(chunk_id, 余弦相似度)]，按相似度倒序。"""
    global _index
    with _lock:
        if _index is None:
            _index = _build()
        index = _index

    if index.ntotal == 0:
        return []

    k = max(1, min(int(k), int(index.ntotal)))
    scores, ids = index.search(
        np.asarray([vector], dtype=np.float32), k,
    )
    return [
        (int(cid), float(score))
        for cid, score in zip(ids[0], scores[0])
        if cid != -1
    ]
