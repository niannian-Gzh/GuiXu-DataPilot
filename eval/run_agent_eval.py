import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from llm import LLM
from agent import run_agent
from session import Session
from trace import Trace
from services import UserInputRequired
from config import load_config, resolve, resolve_db_url


def eval_one(question, case, llm, db_path, table_name):
    session = Session()
    trace = Trace(question)
    try:
        answer = run_agent(question, session, llm, db_path, table_name, trace)
    except UserInputRequired:
        return False, "意外触发用户确认"
    except Exception as e:
        return False, f"异常：{e}"

    # 全含：所有关键词都要出现
    if "expected_answer_contains" in case:
        for kw in case["expected_answer_contains"]:
            if kw not in answer:
                return False, f"回答中缺少：{kw}（回答：{answer[:80]}）"

    # 任一：命中一个即可
    if "expected_answer_contains_any" in case:
        if not any(kw in answer for kw in case["expected_answer_contains_any"]):
            return False, f"回答中未包含任一关键词：{case['expected_answer_contains_any']}（回答：{answer[:80]}）"

    return True, "OK"


def run():
    cfg = load_config()["data"]
    db_path = resolve_db_url()
    table_name = cfg["table_name"]
    llm = LLM()

    golden_path = Path(__file__).parent / "golden_set_agent.json"
    if not golden_path.exists():
        golden_path = Path(__file__).parent / "golden_set_agent_sample.json"
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    passed = 0
    failed = []

    for case in golden:
        print(f"\n[{case['id']}] {case['question']}")
        ok, reason = eval_one(case["question"], case, llm, db_path, table_name)
        if ok:
            passed += 1
            print("  ✅")
        else:
            failed.append(case["id"])
            print(f"  ❌ {reason}")

    total = len(golden)
    print(f"\n{'=' * 40}")
    print(f"Agent 层评测：{passed}/{total} 通过")
    if failed:
        print(f"失败题号：{failed}")


if __name__ == "__main__":
    run()