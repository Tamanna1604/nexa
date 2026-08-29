"""Turn files on disk into plain text.

Supported: .txt, .md, .pdf. Everything else is skipped with a warning.
"""

from __future__ import annotations

from pathlib import Path

SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".pdf"}


def discover(documents_dir: str) -> list[Path]:
    root = Path(documents_dir)
    if not root.exists():
        return []
    return sorted(
        p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )


def load_file(path: str | Path) -> tuple[str, str]:
    """Return ``(title, text)``. Title defaults to the file stem."""
    path = Path(path)
    suffix = path.suffix.lower()
    title = path.stem.replace("_", " ").replace("-", " ").strip()

    if suffix == ".pdf":
        return title, _load_pdf(path)
    return title, path.read_text(encoding="utf-8", errors="ignore")


def _load_pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        extracted = page.extract_text() or ""
        if extracted.strip():
            pages.append(extracted.strip())
    return "\n\n".join(pages)
