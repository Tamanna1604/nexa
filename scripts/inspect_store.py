"""Peek into what Nexa has stored.

    python -m scripts.inspect_store --memories
    python -m scripts.inspect_store --chunks
    python -m scripts.inspect_store --documents
    python -m scripts.inspect_store --messages
"""

from __future__ import annotations

import argparse

from nexa.config import settings
from nexa.storage import SQLiteStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect Nexa's SQLite store.")
    parser.add_argument("--memories", action="store_true")
    parser.add_argument("--chunks", action="store_true")
    parser.add_argument("--documents", action="store_true")
    parser.add_argument("--messages", action="store_true")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    store = SQLiteStore(settings.DB_PATH)
    store.setup()

    show_all = not (args.memories or args.chunks or args.documents or args.messages)

    if args.memories or show_all:
        print("\n=== MEMORIES ===")
        for m in store.all_memories()[: args.limit]:
            print(f"  [{m.memory_type}/imp{m.importance}/uses{m.use_count}] {m.text}")

    if args.documents or show_all:
        print("\n=== DOCUMENTS ===")
        for d in store.list_documents()[: args.limit]:
            print(f"  {d.title}  <-  {d.path}")

    if args.chunks or show_all:
        print("\n=== CHUNKS ===")
        for c in store.all_chunks()[: args.limit]:
            preview = c.text.replace("\n", " ")[:100]
            print(f"  #{c.ordinal:03d} [{c.title}] {preview}...")

    if args.messages:
        print("\n=== MESSAGES (pass a conversation id via stdin not supported; showing raw) ===")
        conn = store._connect()
        rows = conn.execute(
            "SELECT conversation_id, role, content FROM messages ORDER BY created_at DESC LIMIT ?",
            (args.limit,),
        ).fetchall()
        conn.close()
        for r in rows:
            print(f"  ({r['conversation_id'][:8]}) {r['role']}: {r['content'][:100]}")


if __name__ == "__main__":
    main()
