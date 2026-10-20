"""评测入口。

    uv run python eval/run.py --list
    uv run python eval/run.py --suite offline
    uv run python eval/run.py --suite agent -v
    uv run python eval/run.py --dim D4

默认只跑离线套件：它不花钱、秒级、可以反复跑。
Agent 套件真调模型，**跑之前先确认 key 可用、余额够**。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import harness  # noqa: E402


def _load_suites(with_agent: bool):
    import suites.attacks      # noqa: F401
    import suites.writes       # noqa: F401
    import suites.integrity    # noqa: F401
    import suites.edges        # noqa: F401
    import suites.resilience   # noqa: F401
    if with_agent:
        import suites.agent_tools  # noqa: F401


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="归墟评测")
    parser.add_argument("--suite", choices=("offline", "agent", "all"),
                        default="offline", help="跑哪一档（默认 offline）")
    parser.add_argument("--dim", help="只跑某个维度，如 D4")
    parser.add_argument("--case", help="只跑 id 包含这个字符串的用例")
    parser.add_argument("--list", action="store_true", help="只列用例，不跑")
    parser.add_argument("--keep", action="store_true", help="保留沙箱目录")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="失败时打印完整堆栈")
    args = parser.parse_args()

    _load_suites(with_agent=args.suite in ("agent", "all"))

    cases = list(harness.CASES)
    if args.suite != "all":
        cases = [c for c in cases if c.suite == args.suite]
    if args.dim:
        cases = [c for c in cases if c.dim == args.dim.upper()]
    if args.case:
        cases = [c for c in cases if args.case in c.id]

    if args.list:
        for c in cases:
            print(f"[{c.suite}/{c.dim}] {c.id:<40} {c.title}")
        print(f"\n共 {len(cases)} 条")
        return 0

    if not cases:
        print("没有匹配的用例。用 --list 看看有哪些。")
        return 2

    return harness.run(cases, keep=args.keep, verbose=args.verbose)


if __name__ == "__main__":
    raise SystemExit(main())
