from llm import LLM
from session import Session
from agent import run_agent
from trace import Trace
from config import load_config, resolve
from cleanup import cleanup
from tools import UserInputRequired
from delete_op import (
    format_candidates, delete_confirm_prompt,
    is_confirm, is_cancel, is_bulk_confirm, execute_delete,
    BULK_THRESHOLD,
)
from update_op import execute_update, format_update_confirm
from create_op import (
    execute_create, format_create_confirm,
    execute_batch_create, format_batch_create_confirm,
)


def handle_pending(session, question, trace, db_path, real_table) -> bool:
    """处理待确认操作。返回 True 表示已处理。"""
    pending = session.get_pending()
    if not pending:
        return False

    # 通用：取消
    if is_cancel(question):
        session.clear_pending()
        print(f"\n[回答]\n已取消操作。\n")
        return True

    # ============ CREATE 分支 ============
    if pending.get("type") == "create":
        if is_confirm(question):
            execute_create(
                pending["record"], db_path, real_table,
                pending["trace_id"], pending["user_input"],
            )
            session.clear_pending()
            print(f"\n[回答]\n已新增项目「{pending['record']['project_name']}」。\n")
        else:
            print(f"\n[回答]\n请回复「确认」执行新增，或「取消」放弃。\n")
        return True

    # ============ BATCH_CREATE 分支 ============
    if pending.get("type") == "batch_create":
        n = len(pending["records"])
        if n <= BULK_THRESHOLD:
            valid = is_confirm(question)
        else:
            valid = is_bulk_confirm(question, n)

        if valid:
            count = execute_batch_create(
                pending["records"], db_path, real_table,
                pending["trace_id"], pending["user_input"],
            )
            session.clear_pending()
            print(f"\n[回答]\n已新增 {count} 条记录。\n")
        elif is_cancel(question):
            session.clear_pending()
            print(f"\n[回答]\n已取消新增操作。\n")
        else:
            print(f"\n[回答]\n确认未通过。请重新输入正确的确认信息，或回复「取消」。\n")
        return True
    
    # ============ UPDATE 分支 ============
    if pending.get("type") == "update":
        n = len(pending["candidates"])
        if n <= BULK_THRESHOLD:
            valid = is_confirm(question)
        else:
            valid = is_bulk_confirm(question, n)

        if valid:
            count = execute_update(
                pending["candidates"], pending["updates"], db_path, real_table,
                pending["trace_id"], pending["user_input"],
            )
            session.clear_pending()
            print(f"\n[回答]\n已修改 {count} 条记录。\n")
        elif is_cancel(question):
            session.clear_pending()
            print(f"\n[回答]\n已取消修改操作。\n")
        else:
            print(f"\n[回答]\n确认未通过。请重新输入正确的确认信息，或回复「取消」。\n")
        return True

    # ============ DELETE 分支（原有逻辑） ============
    n = len(pending["candidates"])
    if n <= BULK_THRESHOLD:
        valid = is_confirm(question)
    else:
        valid = is_bulk_confirm(question, n)

    if valid:
        count = execute_delete(
            pending["candidates"], db_path, real_table,
            pending["trace_id"], pending["user_input"],
        )
        session.clear_pending()
        print(f"\n[回答]\n已删除 {count} 条记录。7 天内可恢复。\n")
    else:
        print(f"\n[回答]\n确认未通过。请重新输入正确的确认信息，或回复「取消」。\n")
    return True




def main():
    cfg = load_config()["data"]
    db_path = resolve(cfg["db_path"])
    real_table = f"{cfg['table_name']}_all"
    llm = LLM()
    session = Session()

    cleanup()

    print("DataPilot · 数据领航员（Agent 版）")
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
            if handle_pending(session, question, trace, db_path, real_table):
                continue

            answer = run_agent(question, session, llm, db_path, cfg["table_name"], trace)
            print(f"\n[回答]\n{answer}\n")
        except UserInputRequired as e:
            pending = e.pending_action
            session.set_pending(pending)

            if pending["type"] == "delete":
                msg = format_candidates(pending["candidates"])
                msg += "\n\n" + delete_confirm_prompt(pending["candidates"])
            elif pending["type"] == "create":
                msg = format_create_confirm(pending["record"])
            elif pending["type"] == "batch_create":
                msg = format_batch_create_confirm(pending["records"])
            elif pending["type"] == "update":
                msg = format_update_confirm(pending["candidates"], pending["updates"])
            else:
                msg = "需要用户确认"
            print(f"\n[回答]\n{msg}\n")
        except Exception as e:
            trace.set("error", str(e))
            print(f"[错误] {e}\n")
        finally:
            trace.mark_end()
            trace.save()


if __name__ == "__main__":
    main()