import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import load_config, resolve
from llm import LLM
from nl2sql import get_schema, generate_sql_with_retry
from execute import execute_sql


def check(df, case):
    if "expected_rows" in case:
        if len(df) != case["expected_rows"]:
            return False, f"行数不符：期望 {case['expected_rows']}，实际 {len(df)}"

    if "expected_answer_contains" in case:
        text = df.to_string()
        for kw in case["expected_answer_contains"]:
            if kw not in text:
                return False, f"结果中缺少：{kw}"

    return True, "OK"


def run():
    cfg = load_config()["data"]
    db_path = resolve(cfg["db_path"])
    llm = LLM()
    schema = get_schema(db_path, cfg["table_name"])

    golden_path = Path(__file__).parent / "golden_set.json"
    if not golden_path.exists():
        golden_path = Path(__file__).parent / "golden_set_sample.json"
    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    passed = 0
    first_try_pass = 0
    retried = []
    failed = []

    for case in golden:
        print(f"\n[{case['id']}] {case['question']}")
        try:
            sql, retries = generate_sql_with_retry(
                case["question"], llm, schema, db_path, cfg["table_name"], max_retries=2
            )
            if retries == 0:
                first_try_pass += 1
            else:
                retried.append(case["id"])

            df = execute_sql(sql, db_path)
            ok, reason = check(df, case)

            if ok:
                passed += 1
                mark = "✅" if retries == 0 else f"✅（重试 {retries} 次）"
                print(f"  {mark}")
            else:
                failed.append(case["id"])
                print(f"  ❌ {reason}")
                print(f"     SQL: {sql}")
        except Exception as e:
            failed.append(case["id"])
            print(f"  ❌ 异常：{e}")

    total = len(golden)
    print(f"\n{'=' * 40}")
    print(f"结果：{passed}/{total} 通过")
    print(f"健康度：{first_try_pass}/{total} 一次通过")
    if retried:
        print(f"重试题号：{retried}")
    if failed:
        print(f"失败题号：{failed}")


if __name__ == "__main__":
    run()