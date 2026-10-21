"""文档库子系统：把非结构化资料变成可检索的切片。

**它不是"工具"，是一个子系统。** 工具层只露一个动作——检索
（`search_documents`）；上传、解析、分块、建索引、删文档都在这里，
由前端文档库页直接调用，不经过模型。

## 三样东西各归各

| 东西 | 存哪 | 能不能重来 |
|---|---|---|
| 切片原文 | SQLite `_gx_chunk.text` | **不能**——丢了就是丢了 |
| 向量 | SQLite `_gx_chunk.embedding`（BLOB） | 能（原文 + 模型重算） |
| 索引 | FAISS（内存） | 能——拿向量重建 |

**SQLite 永远是唯一真源，FAISS 永远是派生索引。** 写只写 SQLite，
索引在启动时或数据变更后重建。删文档只删 SQLite 一个事务，索引下一个
版本自然不含它——跨存储没有事务，所以能对上的只能有一份。

## 为什么用 `_gx_` 前缀

文档库是语料，不是数据源。放进 `list_tables` 会让数据字典、导出、
垃圾桶、闸门都多出一类不该碰的东西。系统表前缀把它们藏起来：
模型看不见，只能通过检索工具读。
"""

from __future__ import annotations

from config import PROJECT_ROOT

# 原文件与权重。两个都是模块常量，评测的沙箱会替换 DOC_DIR
DOC_DIR = PROJECT_ROOT / "data" / "documents"
MODEL_DIR = PROJECT_ROOT / "models" / "bge-small-zh-v1.5"

DOC_TABLE = "_gx_doc"
CHUNK_TABLE = "_gx_chunk"

# bge-small-zh-v1.5 的输出维度。写死不是为了省一次读取——空库时没有
# 向量可读，建 FAISS 索引仍然要知道维度
DIM = 512

# 扩展名 → 解析器。`.doc` 是老二进制格式，pypdf/python-docx 都不管，
# 明确拒绝好过解析出一堆乱码
SUPPORTED = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "text",
    ".md": "text",
}


class RagError(Exception):
    """文档库的业务错误：格式不支持、没有可提取文字、重复上传……"""


def ensure_meta(con) -> None:
    """建两张系统表。幂等，连库时调用（和 storage/snapshot 的 meta 一样）。"""
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {DOC_TABLE} ("
        "  id        INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  name      TEXT NOT NULL,"          # 用户看到的原始文件名
        "  path      TEXT NOT NULL,"          # DOC_DIR 下的文件名，不带目录
        "  kind      TEXT NOT NULL,"
        "  size      INTEGER NOT NULL,"
        "  sha256    TEXT NOT NULL UNIQUE,"   # 重复上传靠它挡
        "  added_at  TEXT NOT NULL,"
        "  is_deleted INTEGER NOT NULL DEFAULT 0,"
        "  deleted_at TEXT)"
    )
    # 旧库没有这两列。CREATE IF NOT EXISTS 不会补列，得自己迁移
    _ensure_column(con, "is_deleted", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(con, "deleted_at", "TEXT")
    con.execute(
        f"CREATE TABLE IF NOT EXISTS {CHUNK_TABLE} ("
        "  id        INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  doc_id    INTEGER NOT NULL,"
        "  seq       INTEGER NOT NULL,"       # 在文档里的顺序，回看时用
        "  text      TEXT NOT NULL,"
        "  embedding BLOB NOT NULL)"
    )
    # 删文档要按 doc_id 一次清干净；没有这个索引，文档一多就是全表扫
    con.execute(
        f"CREATE INDEX IF NOT EXISTS {CHUNK_TABLE}_doc ON {CHUNK_TABLE}(doc_id)"
    )


def _ensure_column(con, column: str, ddl: str) -> None:
    cols = {r[1] for r in con.execute(f"PRAGMA table_info({DOC_TABLE})")}
    if column not in cols:
        con.execute(f"ALTER TABLE {DOC_TABLE} ADD COLUMN {column} {ddl}")
