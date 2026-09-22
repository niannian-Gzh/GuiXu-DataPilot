"""数据库抽象层。

所有需要访问数据源的代码，都通过这一层，不直接调 duckdb / sqlalchemy。
目的：把"DuckDB vs PG"的差异收敛在这一个文件里。

后端由 config.yaml 的 data.db_url 决定：
  duckdb:///data/xxx.duckdb     → DuckDB 本地文件
  postgresql://user:pass@host   → Postgres
"""

import duckdb
from config import resolve_db_url
import re
from contextlib import contextmanager


def _backend() -> str:
    url = resolve_db_url()
    if (url.startswith("postgresql://")
            or url.startswith("postgresql+psycopg2://")
            or url.startswith("postgresql+psycopg://")):
        return "postgres"
    return "duckdb"


def _pg_url() -> str:
    """SQLAlchemy 要求的 PG URL 要显式指定驱动。

    用 psycopg（第三版）——psycopg2 在中文 Windows 上有个编码 bug：
    连接失败时把 GBK 错误文本按 UTF-8 解码，崩在"展示错误"这一步，
    真实错误被掩盖（比如"密码错误"会变成"UnicodeDecodeError"）。
    """
    url = resolve_db_url()
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql+psycopg2://"):
        return url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)
    return url


def _adapt_params_for_pg(sql: str, params):
    """把位置参数 ? 转成 SQLAlchemy 的命名参数 :p0 / :p1。

    只在 PG 后端调用。DuckDB 原生认 ?，不用转。

    局限：不处理字符串字面量里的 ?。本项目 SQL 都是模板拼的，
    ? 只作占位符，暂时不碰这个边界。
    """
    if params is None:
        return sql, {}
    if isinstance(params, dict):
        return sql, params
    idx = 0
    def _repl(_):
        nonlocal idx
        key = f"p{idx}"
        idx += 1
        return f":{key}"
    new_sql = re.sub(r"\?", _repl, sql)
    new_params = {f"p{i}": v for i, v in enumerate(params)}
    return new_sql, new_params


def query_df(sql: str, params=None, timeout: int = None):
    """执行查询，返回 pandas DataFrame。

    timeout: 秒。None 表示不限。超时机制后端各自实现。
    """
    if _backend() == "duckdb":
        import threading
        con = duckdb.connect(resolve_db_url(), read_only=True)
        timer = None
        if timeout:
            timer = threading.Timer(timeout, con.interrupt)
            timer.start()
        try:
            if params is not None:
                return con.execute(sql, params).fetchdf()
            return con.execute(sql).fetchdf()
        except Exception as e:
            if timeout and "interrupt" in str(e).lower():
                raise TimeoutError(f"SQL 查询超过 {timeout} 秒，已中断")
            raise
        finally:
            if timer:
                timer.cancel()
            con.close()

    # PG
    import pandas as pd
    from sqlalchemy import create_engine, text
    engine = create_engine(_pg_url())
    with engine.connect() as conn:
        if timeout:
            conn.execute(text(f"SET statement_timeout = {timeout * 1000}"))
        adapted_sql, adapted_params = _adapt_params_for_pg(sql, params)
        result = conn.execute(text(adapted_sql), adapted_params)
        rows = result.fetchall()
        cols = list(result.keys())
        return pd.DataFrame(rows, columns=cols)


def execute(sql: str, params=None) -> int:
    """执行 DDL/DML。返回受影响行数（PG 准确，DuckDB 返回 0）。"""
    if _backend() == "duckdb":
        con = duckdb.connect(resolve_db_url())
        try:
            if params is not None:
                con.execute(sql, params)
            else:
                con.execute(sql)
            return 0
        finally:
            con.close()

    # PG
    from sqlalchemy import create_engine, text
    engine = create_engine(_pg_url())
    with engine.begin() as conn:
        adapted_sql, adapted_params = _adapt_params_for_pg(sql, params)
        result = conn.execute(text(adapted_sql), adapted_params)
        return result.rowcount or 0


def execute_many(sql: str, rows: list) -> int:
    """批量执行（插入多行）。rows 是列表，每项是一个元组。"""
    if _backend() == "duckdb":
        con = duckdb.connect(resolve_db_url())
        try:
            con.executemany(sql, rows)
            return len(rows)
        finally:
            con.close()

    # PG
    from sqlalchemy import create_engine, text
    if not rows:
        return 0
    # SQL 的占位符结构每行一样，转一次即可；每行的参数各自映射成 dict
    adapted_sql, _ = _adapt_params_for_pg(sql, rows[0])
    adapted_rows = []
    for row in rows:
        _, adapted = _adapt_params_for_pg(sql, row)
        adapted_rows.append(adapted)

    engine = create_engine(_pg_url())
    with engine.begin() as conn:
        conn.execute(text(adapted_sql), adapted_rows)
        return len(rows)

def describe(table: str) -> list:
    """读表结构。

    返回 [{"name": str, "type": str, "nullable": bool}, ...]
    nullable=True 表示允许 NULL；False 表示 NOT NULL（必填）。
    """
    if _backend() == "duckdb":
        con = duckdb.connect(resolve_db_url(), read_only=True)
        try:
            df = con.execute(f"DESCRIBE {table}").fetchdf()
        finally:
            con.close()
        # DuckDB 的 DESCRIBE 返回六列：column_name / column_type /
        # null / key / default / extra。按列名读，不按位置——
        # 列顺序可能随版本变
        return [
            {
                "name": row["column_name"],
                "type": row["column_type"],
                "nullable": str(row["null"]).upper() == "YES",
            }
            for _, row in df.iterrows()
        ]

    # PG
    from sqlalchemy import create_engine, text
    engine = create_engine(_pg_url())
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_name = :t "
            "ORDER BY ordinal_position"
        ), {"t": table})
        return [
            {
                "name": r[0],
                "type": r[1],
                "nullable": (r[2] == "YES"),
            }
            for r in result.fetchall()
        ]


def list_tables() -> list:
    """列出当前库里的所有表。

    只返回表，不含视图——视图是派生对象，不该出现在"数据字典"里让用户标注。
    """
    if _backend() == "duckdb":
        con = duckdb.connect(resolve_db_url(), read_only=True)
        try:
            df = con.execute("SHOW TABLES").fetchdf()
        finally:
            con.close()
        # 排除视图
        names = df["name"].tolist() if "name" in df.columns else []
        # DuckDB 的 SHOW TABLES 会同时列出表和视图。用 information_schema 区分
        con = duckdb.connect(resolve_db_url(), read_only=True)
        try:
            tables_df = con.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'main' AND table_type = 'BASE TABLE'"
            ).fetchdf()
        finally:
            con.close()
        return sorted(tables_df["table_name"].tolist())

    # PG
    from sqlalchemy import create_engine, text
    engine = create_engine(_pg_url())
    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ))
        return [r[0] for r in result.fetchall()]


class _TxHandle:
    """事务里用的句柄——只有 execute 一个方法。"""
    def __init__(self, execute_fn):
        self._execute = execute_fn

    def execute(self, sql: str, params=None):
        return self._execute(sql, params)


@contextmanager
def transaction():
    """事务上下文。用法：

        with transaction() as tx:
            tx.execute("INSERT ...", [a, b])
            tx.execute("UPDATE ...", [c])
        # 正常退出自动 COMMIT，异常自动 ROLLBACK

    后端差异：
      DuckDB  → 显式 BEGIN / COMMIT / ROLLBACK
      PG      → SQLAlchemy 的 engine.begin() 自动管理
    """
    if _backend() == "duckdb":
        con = duckdb.connect(resolve_db_url())

        def _exec(sql, params=None):
            if params is not None:
                return con.execute(sql, params)
            return con.execute(sql)

        handle = _TxHandle(_exec)
        try:
            con.execute("BEGIN TRANSACTION")
            yield handle
            con.execute("COMMIT")
        except Exception:
            try:
                con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()
    else:
        from sqlalchemy import create_engine, text
        engine = create_engine(_pg_url())

        with engine.begin() as _conn:
            def _exec(sql, params=None):
                adapted_sql, adapted_params = _adapt_params_for_pg(sql, params)
                return _conn.execute(text(adapted_sql), adapted_params)

            yield _TxHandle(_exec)


def get_engine():
    """返回一个 SQLAlchemy engine。仅 PG 后端可用。

    给需要"和 SQLAlchemy 直接打交道"的场景用——比如 ingest 的 to_sql。
    普通查询走 query_df / execute 就够了，不需要这个。
    """
    if _backend() != "postgres":
        raise RuntimeError("get_engine() 只在 PG 后端可用")
    from sqlalchemy import create_engine
    return create_engine(_pg_url())


def raw():
    """逃生口——只在需要 DuckDB 特有功能时使用（比如 register）。

    用它意味着"这段代码绑死了 DuckDB"，PG 后端下会直接报错。
    """
    if _backend() == "duckdb":
        return duckdb.connect(resolve_db_url())
    raise NotImplementedError("raw() 目前只支持 DuckDB 后端")