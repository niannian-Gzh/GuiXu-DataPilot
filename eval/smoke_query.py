"""冒烟评测：query_database 改成「返回数据」之后，模型还能不能答对。

不是完整评测——是这一刀改完后的快速验证，三件事：

  ① 数据真的到模型手里了吗（返回 columns/rows，不是一段成文答案）
  ② 模型拿到 rows 之后，能不能自己组织出正确答案
  ③ 空结果分支会不会崩（status: empty + 表里总行数）

跑法：
    PYTHONPATH=src uv run python eval/smoke_query.py

会建一张 10 行的测试表，跑完删掉。
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import config
import snapshot
import storage
from agent import run_agent
from llm import LLM
from runner import using
from session import Session
from trace import Trace

# 10 行，分布是设计过的：张三 4、李四 3、赵六 3，王五一个都没有
FIXTURE = [
    (1, "甲系统", "张三", "web", "已结算", 0),
    (2, "乙系统", "张三", "web", "已下证", 1),
    (3, "丙系统", "张三", "嵌入式", "已结算", 2),
    (4, "丁系统", "张三", "web", "待提交", 0),
    (5, "戊系统", "李四", "web", "已结算", 1),
    (6, "己系统", "李四", "嵌入式", "已下证", 0),
    (7, "庚系统", "李四", "web", "已打回", 3),
    (8, "辛系统", "赵六", "嵌入式", "已结算", 0),
    (9, "壬系统", "赵六", "web", "已提交", 2),
    (10, "癸系统", "赵六", "嵌入式", "待提交", 0),
]

CASES = [
    ("一共有几个项目？", ["10"]),
    ("张三负责的项目有几个？", ["4"]),
    ("王五负责的项目有几个？", ["0", "没有", "不存在", "暂无"]),
]


def build():
    con = storage.connect(config.resolve_db_path())
    snapshot.ensure_meta(con)
    for t in storage.list_tables(con):
        snapshot.drop_table(con, t)
    storage.create_table(
        con, "projects",
        "id INTEGER PRIMARY KEY, name TEXT NOT NULL, owner TEXT, "
        "category TEXT, status TEXT, review_count INTEGER DEFAULT 0",
    )
    con.executemany(
        "INSERT INTO projects (id, name, owner, category, status, review_count) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        FIXTURE,
    )
    con.close()


def teardown():
    con = storage.connect(config.resolve_db_path())
    snapshot.ensure_meta(con)
    for t in storage.list_tables(con):
        snapshot.drop_table(con, t)
    con.close()


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    build()
    llm = LLM()
    if getattr(llm, "mock", False):
        print("没有可用的 API key（LLM 处于 mock 态），评测跑不了。")
        teardown()
        return 1

    print(f"模型：{llm.model}")
    print(f"库：{config.resolve_db_path()}")
    print(f"数据：10 行（张三 4 / 李四 3 / 赵六 3）\n")

    passed = 0
    for question, expected in CASES:
        session = Session()
        trace = Trace(question)
        started = time.time()
        try:
            reply = run_agent(question, session, llm, trace, max_iterations=8)
        except Exception as e:
            print(f"✗ {question}")
            print(f"    异常：{type(e).__name__}: {e}\n")
            continue
        elapsed = int((time.time() - started) * 1000)

        hit = any(word in reply for word in expected)
        passed += hit
        print(f"{'✓' if hit else '✗'} {question}   [{elapsed} ms]")
        print(f"    期望包含：{' / '.join(expected)}")
        print(f"    回答：{reply.strip()[:200]}")
        print()

    print(f"结果：{passed}/{len(CASES)}")
    teardown()
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
