"""业务凭据：谁、何时、改了什么。

**进数据库，不进文件。** 改库和记审计必须同生共死——
改成功但审计写失败 = 没账；审计写了但库没改 = 假账。
所以 `record()` 收的是事务句柄，调用方在改完之后、提交之前写。

`log()` 是给「没有事务可依附」的动作的（导出是只读，清理是系统任务），
它自己开连接、自己包一个事务。

观测日志（trace）还是留在文件里：它记的是「这次跑得怎么样」，
不是「谁改了什么」。性质不同，去处不同。
"""

import json
from datetime import datetime

import storage
from config import resolve_db_path


def record(handle, action: str, detail: dict):
    """在**调用方的事务里**写一条审计。

    handle 是连接或 `runner._Handle`——两者都有 execute，
    鸭子类型够用，不必为它加一层接口。
    """
    handle.execute(
        f"INSERT INTO {storage.AUDIT} (at, action, trace_id, user_input, tbl, detail) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now().isoformat(timespec="seconds"),
            action,
            detail.get("trace_id"),
            detail.get("user_input"),
            detail.get("table"),
            json.dumps(detail, ensure_ascii=False, default=str),
        ),
    )


def log(action: str, detail: dict):
    """没有事务可依附时，自己开连接写。"""
    con = storage.connect(resolve_db_path())
    try:
        con.execute("BEGIN")
        record(con, action, detail)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()
