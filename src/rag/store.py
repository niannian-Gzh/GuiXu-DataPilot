"""文档库的 SQLite 读写。

**唯一真源。** 文档、切片、向量都在这里；FAISS 只是它的一份派生索引。
所有函数收连接/事务句柄（鸭子类型），事务边界由调用方定——
上传是"元信息 + 切片"一起成，删文档是"级联删"一起成。

**删除是软删**：文档和切片都留着，只把 `is_deleted` 置 1；检索、列表、
索引重建都会过滤掉。物理清理由保留期任务负责。
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from rag import CHUNK_TABLE, DOC_TABLE


def find_by_sha(con, sha256: str):
    """重复上传检查要连已软删的一起看——删掉的文档重新上传应该恢复，
    而不是被 sha 挡住（恢复走 restore，不重复灌切片）。"""
    return con.execute(
        f"SELECT id, name, is_deleted FROM {DOC_TABLE} WHERE sha256 = ?", (sha256,)
    ).fetchone()


def add(con, *, name: str, path: str, kind: str, size: int,
        sha256: str, chunks: list[str], vectors: np.ndarray) -> int:
    cur = con.execute(
        f"INSERT INTO {DOC_TABLE} (name, path, kind, size, sha256, added_at) "
        f"VALUES (?, ?, ?, ?, ?, ?)",
        (name, path, kind, size, sha256,
         datetime.now().isoformat(timespec="seconds")),
    )
    doc_id = int(cur.lastrowid)
    # 事务句柄的方法叫 execute_many（和 runner._Handle 对齐）
    con.execute_many(
        f"INSERT INTO {CHUNK_TABLE} (doc_id, seq, text, embedding) "
        f"VALUES (?, ?, ?, ?)",
        [
            (doc_id, seq, text, vectors[seq].astype(np.float32).tobytes())
            for seq, text in enumerate(chunks)
        ],
    )
    return doc_id


def list_docs(con, deleted: bool = False) -> list[dict]:
    flag = 1 if deleted else 0
    rows = con.execute(
        f"SELECT d.id, d.name, d.kind, d.size, d.added_at, d.deleted_at, "
        f"       COUNT(c.id) "
        f"FROM {DOC_TABLE} d LEFT JOIN {CHUNK_TABLE} c ON c.doc_id = d.id "
        f"WHERE d.is_deleted = ? "
        f"GROUP BY d.id ORDER BY d.id DESC",
        (flag,),
    ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "kind": r[2], "size": r[3],
            "added_at": r[4], "deleted_at": r[5], "chunks": r[6],
        }
        for r in rows
    ]


def get_doc(con, doc_id: int):
    return con.execute(
        f"SELECT id, name, path, kind, size, is_deleted, deleted_at, added_at "
        f"FROM {DOC_TABLE} WHERE id = ?",
        (doc_id,),
    ).fetchone()


def soft_delete(con, doc_id: int) -> None:
    con.execute(
        f"UPDATE {DOC_TABLE} SET is_deleted = 1, deleted_at = ? WHERE id = ?",
        (datetime.now().isoformat(timespec="seconds"), doc_id),
    )


def restore(con, doc_id: int) -> None:
    con.execute(
        f"UPDATE {DOC_TABLE} SET is_deleted = 0, deleted_at = NULL WHERE id = ?",
        (doc_id,),
    )


def purge(con, doc_id: int) -> int:
    """物理删除：切片先走，再走文档。返回删掉的切片数。"""
    cur = con.execute(f"DELETE FROM {CHUNK_TABLE} WHERE doc_id = ?", (doc_id,))
    removed = cur.rowcount
    con.execute(f"DELETE FROM {DOC_TABLE} WHERE id = ?", (doc_id,))
    return removed


def counts(con) -> dict:
    """左栏读数只算活着的：软删的不该算进「N 份 · M 块」。"""
    docs = con.execute(
        f"SELECT COUNT(*) FROM {DOC_TABLE} WHERE is_deleted = 0"
    ).fetchone()[0]
    chunks = con.execute(
        f"SELECT COUNT(*) FROM {CHUNK_TABLE} c "
        f"JOIN {DOC_TABLE} d ON d.id = c.doc_id WHERE d.is_deleted = 0"
    ).fetchone()[0]
    deleted = con.execute(
        f"SELECT COUNT(*) FROM {DOC_TABLE} WHERE is_deleted = 1"
    ).fetchone()[0]
    return {"docs": int(docs), "chunks": int(chunks), "deleted": int(deleted)}


def expired(con, cutoff: str) -> list[tuple]:
    """超过保留期的软删文档：(id, name, path)。"""
    return con.execute(
        f"SELECT id, name, path FROM {DOC_TABLE} "
        f"WHERE is_deleted = 1 AND deleted_at IS NOT NULL AND deleted_at < ?",
        (cutoff,),
    ).fetchall()


def chunks_by_ids(con, ids: list[int]) -> dict[int, dict]:
    """按需取回原文。已软删的文档不返回——索引可能还留着旧向量。"""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = con.execute(
        f"SELECT c.id, c.doc_id, c.seq, c.text, d.name "
        f"FROM {CHUNK_TABLE} c JOIN {DOC_TABLE} d ON d.id = c.doc_id "
        f"WHERE c.id IN ({marks}) AND d.is_deleted = 0",
        ids,
    ).fetchall()
    return {
        r[0]: {"chunk_id": r[0], "doc_id": r[1], "seq": r[2],
               "text": r[3], "doc": r[4]}
        for r in rows
    }


def chunks_of_doc(con, doc_id: int) -> list[dict]:
    rows = con.execute(
        f"SELECT seq, text FROM {CHUNK_TABLE} WHERE doc_id = ? ORDER BY seq",
        (doc_id,),
    ).fetchall()
    return [{"seq": r[0], "text": r[1]} for r in rows]
