from llm import LLM
from session import Session
from agent import run_agent
from trace import Trace
from config import load_config, resolve, resolve_db_url
from config_store import migrate_if_needed
from cleanup import cleanup
from services import UserInputRequired
from services import pending_service


def main():
    # CLI 也可能先于 web 启动，迁移放这儿，
    # 否则第一次跑 CLI 会因为没有 configs.json 而建不出 LLM
    if migrate_if_needed():
        print("[迁移] config.yaml 的 llm 段已转成第一张模型配置\n")

    cfg = load_config()["data"]
    db_path = resolve_db_url()
    real_table = f"{cfg['table_name']}_all"
    llm = LLM()
    session = Session()

    cleanup()

    print("DataPilot · 数据处理 Agent")
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
            # 优先处理待确认操作
            handled, msg = pending_service.handle_pending(question, session, db_path, real_table, llm)
            if handled:
                print(f"\n[回答]\n{msg}\n")
                continue

            answer = run_agent(question, session, llm, db_path, cfg["table_name"], trace)
            print(f"\n[回答]\n{answer}\n")
        except UserInputRequired as e:
            pending = e.pending_action
            session.set_pending(pending)
            msg = pending_service.format_pending_display(pending)
            print(f"\n[回答]\n{msg}\n")
        except Exception as e:
            trace.set("error", str(e))
            print(f"[错误] {e}\n")
        finally:
            trace.mark_end()
            trace.save()


if __name__ == "__main__":
    main()