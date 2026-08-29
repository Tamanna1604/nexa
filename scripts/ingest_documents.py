"""Bulk-ingest the documents folder (or a path you pass).

    python -m scripts.ingest_documents
    python -m scripts.ingest_documents ./somewhere/else
    python -m scripts.ingest_documents ./notes/plan.md
"""

from __future__ import annotations

import sys
from pathlib import Path

from nexa.brain import build_nexa


def main(argv: list[str]) -> None:
    target = Path(argv[0]) if argv else None
    bundle = build_nexa()
    bundle.store.setup()

    if target and target.is_file():
        results = [bundle.ingestion.ingest_file(target)]
    else:
        results = bundle.ingestion.ingest_directory(str(target) if target else None)

    total = 0
    for r in results:
        total += r.chunks
        line = f"  {r.status:9s} {Path(r.path).name}"
        if r.chunks:
            line += f"  ({r.chunks} chunks)"
        if r.detail:
            line += f"  - {r.detail}"
        print(line)

    bundle.sparse.rebuild(bundle.store.all_chunks())
    print(f"\nDone. {len(results)} file(s) processed, {total} new chunk(s).")
    print(f"Corpus now holds {len(bundle.store.all_chunks())} chunk(s).")


if __name__ == "__main__":
    main(sys.argv[1:])
