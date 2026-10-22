"""数据库结构版本与迁移。

**1.0 是基线：`CURRENT_SCHEMA = 1`，迁移表为空。**
这一步不改任何表，只把新库和老库都标成 1；以后 1.1 加 `2`，
1.2 加 `3`，每次只往 `MIGRATIONS` 里追加一个函数。

规则（写进代码，不靠记性）：

1. **只增不删**：`ADD COLUMN`（带默认值）、`CREATE TABLE`、分批回填；
   不 DROP、不重建、不重命名已有列。要换语义就新建表搬数据，旧表先留。
2. **迁移前备份**：用 SQLite 的 backup API 复制到 `data/../backups/`，
   保留最近几份。迁移在事务里跑，失败回滚；备份是最后退路。
3. **库比程序新就拒绝**：用户装回旧版本时，旧程序看到
   `user_version > CURRENT_SCHEMA` 必须报错，不能硬改新库。
4. **版本号只在这里改**：`CURRENT_SCHEMA` 和 `MIGRATIONS` 是唯一来源；
   不要在别处写 `PRAGMA user_version = ...`。
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

CURRENT_SCHEMA = 1

# 版本号 -> 函数。1.0 没有迁移；以后示例：
#   MIGRATIONS = {2: _migrate_to_2}
MIGRATIONS: dict[int, callable] = {}

_BACKUP_KEEP = 3
_lock = threading.Lock()


class SchemaTooNewError(RuntimeError):
    """库的结构版本比当前程序新。"""


class MigrationError(RuntimeError):
    """迁移失败；库已经回滚，备份保留。"""


def schema_version(con: sqlite3.Connection) -> int:
    return int(con.execute("PRAGMA user_version").fetchone()[0])


def check_compatible(con: sqlite3.Connection) -> int:
    """在动任何表之前检查。库比程序新时，连 meta 都不该碰。"""
    version = schema_version(con)
    if version > CURRENT_SCHEMA:
        raise SchemaTooNewError(
            f"数据库结构版本是 {version}，当前程序只支持到 {CURRENT_SCHEMA}。"
            "请安装更新版本的归墟后再打开；不要用旧版本改这份数据。"
        )
    return version


def backup_before_upgrade(con: sqlite3.Connection, db_path: Path,
                          version: int, was_new: bool) -> Path | None:
    """版本落后且不是刚建的空库时，先留一份备份。

    用 `con.backup()` 而不是复制文件：WAL 里的已提交数据也要进去。
    """
    db_path = Path(db_path)
    if was_new or version >= CURRENT_SCHEMA or str(db_path) == ":memory:":
        return None
    if not db_path.exists():
        return None

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = backup_dir / f"guixu-v{version}-{stamp}.db"
    with sqlite3.connect(str(dest)) as target:
        con.backup(target)

    backups = sorted(
        backup_dir.glob("guixu-v*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in backups[_BACKUP_KEEP:]:
        old.unlink(missing_ok=True)
    return dest


def ensure_schema(con: sqlite3.Connection) -> int:
    """把库升到 CURRENT_SCHEMA。调用前应先 check_compatible + 备份。"""
    with _lock:
        version = check_compatible(con)
        if version == CURRENT_SCHEMA:
            return version

        # 不在这里备份：storage.connect 已经在 ensure_meta 之前做过，
        # 那份备份更早、更干净。
        con.execute("BEGIN")
        try:
            for step in range(version + 1, CURRENT_SCHEMA + 1):
                fn = MIGRATIONS.get(step)
                if fn is not None:
                    fn(con)
                # PRAGMA 不吃参数占位符；step 来自本地常量，不是用户输入
                con.execute(f"PRAGMA user_version = {int(step)}")
            con.execute("COMMIT")
        except Exception as e:
            con.execute("ROLLBACK")
            raise MigrationError(
                f"数据库升级到 v{CURRENT_SCHEMA} 失败，已回滚：{e}"
            ) from e
        return CURRENT_SCHEMA
