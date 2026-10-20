"""跑 SQL 的入口：连接、执行、事务。

**这一层只管"把语句跑出去"**——库长什么样归 storage.py。
分家不是洁癖：这里的每件事（超时、批量、事务边界）都是"执行"的
关注点，而 storage 的关注点是"结构"。混在一起，改一个会碰另一个。

数据源只有 SQLite 一个（design 零章定的），所以这里没有后端分支。
旧 db.py 那 322 行里，一半是"PG 和 DuckDB 怎么不一样"——**那些问题
随着换数据源整个消失了**，不是被解决了。

## 连接策略：一次调用一个连接

不搞全局连接池。SQLite 打开一个文件很便宜，而全局连接有两个坑：
它是**连接级**的（事务、临时表都挂在上头），跨线程共享还要自己加锁。
一次调用一个连接，这两个问题都不存在——**代价只是打开文件的开销，而它很小**。

代价是：**多个调用之间不属于同一个事务**。要原子性就用 `transaction()`，
它自己管一个连接。
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager

import storage
from config import resolve_db_path


def connect() -> sqlite3.Connection:
    """开一个新连接，库文件由 config 决定。"""
    return storage.connect(resolve_db_path())


def using(fn, *args, **kwargs):
    """跑一个"要连接"的函数，连接自动开合：

        text = using(storage.render)

    `storage` 的函数一律要 `con`（那样好测、事务边界也清楚），
    但只读一次的调用方不该为这个写三行 try/finally。
    """
    con = connect()
    try:
        return fn(con, *args, **kwargs)
    finally:
        con.close()


def query_df(sql: str, params=None, timeout: int | None = None):
    """跑查询，返回 pandas DataFrame。

    timeout 是秒。靠 `Connection.interrupt()` 实现——它**从另一个线程**
    叫停正在跑的语句，所以配一个 Timer。这是 SQLite 唯一的超时办法，
    没有 `statement_timeout` 那种设置项。
    """
    import pandas as pd

    con = connect()
    timer = None
    if timeout:
        timer = threading.Timer(timeout, con.interrupt)
        timer.start()
    try:
        cur = con.execute(sql, params) if params is not None else con.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return pd.DataFrame(rows, columns=cols)
    except sqlite3.OperationalError as e:
        if timeout and "interrupt" in str(e).lower():
            raise TimeoutError(f"SQL 查询超过 {timeout} 秒，已中断") from e
        raise
    finally:
        if timer:
            timer.cancel()
        con.close()


def execute(sql: str, params=None) -> int:
    """跑 DDL / DML，返回受影响行数。

    DDL 的 rowcount 是 -1，归一成 0——**调用方拿它算"改了几行"，
    负数会让 `affected` 这种字段变得没法解释。**
    """
    con = connect()
    try:
        cur = con.execute(sql, params) if params is not None else con.execute(sql)
        return max(cur.rowcount, 0)
    finally:
        con.close()


def execute_many(sql: str, rows: list) -> int:
    """批量执行（灌多行）。rows 是列表，每项一个元组。返回灌了几行。"""
    if not rows:
        return 0
    con = connect()
    try:
        con.executemany(sql, rows)
        return len(rows)
    finally:
        con.close()


class _Handle:
    """事务句柄。

    `execute` 返回**游标**，不返回行数——跟原生 `sqlite3` 一致。
    原因是事务里既可能写（要 rowcount）也可能读（要 fetchall /
    `PRAGMA table_info` 的迭代），硬把返回值统一成 int 会让后者没法用
    （`'int' object is not iterable`）。要行数的调用方取 `.rowcount` 就行。
    """

    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def execute(self, sql: str, params=None):
        return self._con.execute(sql, params) if params is not None else self._con.execute(sql)

    def execute_many(self, sql: str, rows: list) -> int:
        if not rows:
            return 0
        self._con.executemany(sql, rows)
        return len(rows)

    def query(self, sql: str, params=None) -> list[tuple]:
        cur = self._con.execute(sql, params) if params is not None else self._con.execute(sql)
        return cur.fetchall()


@contextmanager
def transaction():
    """事务上下文：

        with transaction() as tx:
            tx.execute("INSERT ...", [a, b])
            tx.execute("UPDATE ...", [c])
        # 正常退出 COMMIT，异常 ROLLBACK

    **一个连接 = 一个事务**（SQLite 的事务挂在连接上），所以这里必须
    自己开一个，不能跟 query_df / execute 共用心跳。
    """
    con = connect()
    try:
        con.execute("BEGIN")
        yield _Handle(con)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
