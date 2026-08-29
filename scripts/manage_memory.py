"""Inspect and prune Nexa's long-term memory.

    python -m scripts.manage_memory --list
    python -m scripts.manage_memory --forget <memory-id>
    python -m scripts.manage_memory --forget-all
"""

from __future__ import annotations

import argparse

from nexa.brain import build_nexa


def main() -> None:
    parser = argparse.ArgumentParser(description="Manage Nexa long-term memory.")
    parser.add_argument("--list", action="store_true", help="list every stored memory")
    parser.add_argument("--forget", metavar="ID", help="delete one memory by id")
    parser.add_argument("--forget-all", action="store_true", help="delete every memory")
    args = parser.parse_args()

    bundle = build_nexa()
    bundle.store.setup()
    ltm = bundle.nexa.memory.long_term

    if args.forget_all:
        n = ltm.forget_all()
        print(f"Forgot {n} memories.")
        return

    if args.forget:
        print("Forgot it." if ltm.forget(args.forget) else "No memory with that id.")
        return

    # default / --list  -> grouped by type, newest first
    memories = ltm.all()
    if not memories:
        print("No long-term memories stored yet.")
        return

    by_type: dict[str, list] = {}
    for m in memories:
        by_type.setdefault(m.memory_type or "other", []).append(m)

    print(f"{len(memories)} memory(ies) across {len(by_type)} type(s):\n")
    for mtype in sorted(by_type):
        rows = sorted(by_type[mtype], key=lambda m: m.created_at, reverse=True)
        print(f"── {mtype.upper()} ({len(rows)}) " + "─" * 40)
        for m in rows:
            when = (m.created_at or "")[:10]
            print(f"  {m.text}")
            print(f"     importance {m.importance} · recalled {m.use_count}x · {when} · id {m.id}")
        print()


if __name__ == "__main__":
    main()
