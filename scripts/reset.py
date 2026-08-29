"""Wipe Nexa's learned state - conversations, memories, and the document index.

    python -m scripts.reset          # asks for confirmation
    python -m scripts.reset --yes    # no prompt

Your files in documents/ are left untouched; they get re-ingested on next start.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from nexa.config import settings


def main(argv: list[str]) -> None:
    if "--yes" not in argv:
        ans = input("Delete memory.db and chroma_db/ ? [y/N] ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    for path in (Path(settings.DB_PATH), Path(settings.CHROMA_PATH)):
        if path.is_file():
            path.unlink()
            print(f"removed {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            print(f"removed {path}/")
        else:
            print(f"(nothing at {path})")

    print("Done. Run the app to rebuild from documents/.")


if __name__ == "__main__":
    main(sys.argv[1:])
