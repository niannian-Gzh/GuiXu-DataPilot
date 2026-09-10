from llm import LLM
from nl2sql import load_config, get_schema, generate_sql_with_retry
from execute import execute_sql
from summarize import summarize
from session import Session
from rewrite import rewrite
from trace import Trace
from guard import SecurityError
from intent import classify


def main():
    from config import resolve
    cfg = load_config()["data"]
    db_path = resolve(cfg["db_path"])
    llm = LLM()
    schema = get_schema(db_path, cfg["table_name"])
    session = Session()

    print("DataPilot · 数据领航员")
    print("输入问题，exit 退出\n")

    while True:
        question = input("你问：").strip()
        if question.lower() in ("exit", "quit", "退出"):
            print("再见")
            break
        if not question:
            continue

        trace = Trace(question)

        try:
            standalone = rewrite(question, session, llm)
            trace.set("standalone", standalone)
            if standalone != question:
                print(f"  [改写] {standalone}")

            # 意图判断（内部包含写操作检查）
            intent_result = classify(standalone, llm)
            trace.set("intent", intent_result["intent"])

            if intent_result["intent"] in ("CLARIFY", "CHITCHAT"):
                answer = intent_result["message"]
                print(f"\n[回答]\n{answer}\n")
                session.add_user(standalone)
                session.add_assistant(answer)
                continue

            if intent_result["intent"] == "UNSUPPORTED":
                raise SecurityError(intent_result["message"])

            # QUERY：正常走 SQL 流程
            sql, retries = generate_sql_with_retry(
                standalone, llm, schema, db_path, cfg["table_name"], max_retries=2
            )
            trace.set("sql", sql)
            trace.set("retries", retries)

            df = execute_sql(sql, db_path)
            trace.set("row_count", len(df))

            answer = summarize(standalone, df, llm)
            trace.set("answer_len", len(answer))
            trace.set("answer_head", answer[:50])

            session.add_user(standalone)
            session.add_assistant(answer)

            tag = "" if retries == 0 else f"（重试 {retries} 次）"
            print(f"\n[SQL{tag}] {sql}\n")
            print(f"[回答]\n{answer}\n")
            print(f"[trace] {trace.id}\n")
        except SecurityError as e:
            trace.set("error", f"[安全拒绝] {e}")
            print(f"\n[安全拒绝] {e}\n")
        except Exception as e:
            trace.set("error", str(e))
            print(f"[错误] {e}\n")
        finally:
            trace.mark_end()
            trace.save()


if __name__ == "__main__":
    main()