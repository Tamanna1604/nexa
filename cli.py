"""Nexa in the terminal.

Same feel as the original: `remember <something>` stores a memory, `exit`
quits. Everything else is a normal streamed conversation turn. A single
conversation lasts for the life of the process.
"""

from __future__ import annotations

from nexa.brain import build_nexa


def main() -> None:
    bundle = build_nexa()
    print("[nexa] starting up (tables, document ingestion, BM25 index) ...")
    bundle.bootstrap(ingest=True)
    nexa = bundle.nexa
    conversation_id = nexa.start_conversation("cli")

    chunks = len(bundle.store.all_chunks())
    print(f"\nNexa is online.  ({chunks} document chunks indexed)")
    print("Type 'exit' to shut down.")
    print("Use: remember <something>  to store a memory.\n")

    while True:
        try:
            user_message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nNexa: Goodbye.")
            break

        if not user_message:
            continue

        if user_message.lower() == "exit":
            print("Nexa: Goodbye.")
            break

        if user_message.lower().startswith("remember "):
            fact = user_message[9:].strip()
            stored = nexa.memory.long_term.remember(fact, "general", importance=8)
            print("Nexa: I'll remember that.\n" if stored else "Nexa: I already knew that.\n")
            continue

        print("Nexa: ", end="", flush=True)
        sources: list = []
        recalled: list = []
        for event in nexa.respond_stream(user_message, conversation_id):
            if event["type"] == "token":
                print(event["text"], end="", flush=True)
            elif event["type"] == "meta":
                sources = event["sources"]
                recalled = event["memories_recalled"]
        print("\n")

        if sources:
            print("  ── sources ──")
            for s in sources:
                print(f"   [{s['score']:.3f}] {s['title']}: {s['text'][:90]}...")
        if recalled:
            print("  ── recalled memories ──")
            for m in recalled:
                print(f"   ({m['type']}) {m['text']}")
        if sources or recalled:
            print()


if __name__ == "__main__":
    main()
