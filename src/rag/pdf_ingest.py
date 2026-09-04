"""PDF ingestion — real PDFs when present, .txt fallback for CI.

Per ECC iterative-retrieval + python-patterns (EAFP):
- Try pypdf if installed; else fall back to .txt sidecars.
- Chunk by sections (headings / 800-char windows).
- Extract staleness metadata from front-matter lines:
    Doc ID: ..., Still Valid As Of: YYYY-MM-DD, Superseded By: ..., Status: ...

data/rag_docs/ layout (production):
  2011_ont_reset.pdf          # real PDF (optional)
  2011_ont_reset.pdf.txt      # extracted fallback (checked in for CI)
  2011_ont_reset.pdf.meta.json# optional explicit metadata

If no .pdf exists we use .txt so tests stay deterministic with zero deps.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Chunk

DATA_DIR = Path(__file__).parents[2] / "data" / "rag_docs"


def _parse_front_matter(text: str) -> dict:
    meta: dict = {}
    for line in text.splitlines()[:15]:
        m = re.match(r"\s*(Doc ID|Title|Still Valid As Of|Superseded By|Supersedes|Status)\s*:\s*(.+)", line, re.IGNORECASE)
        if m:
            meta[m.group(1).strip().lower()] = m.group(2).strip()
    return meta


def _extract_text(pdf_path: Path, txt_fallback: Path | None = None) -> str:
    # EAFP: try pypdf, else txt
    try:
        if pdf_path.exists() and pdf_path.suffix == ".pdf":
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(str(pdf_path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError:
                pass
    except Exception:
        pass
    if txt_fallback and txt_fallback.exists():
        return txt_fallback.read_text(encoding="utf-8", errors="ignore")
    if pdf_path.exists():
        try:
            return pdf_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return ""
    return ""


def chunk_text(text: str, chunk_size: int = 800) -> list[str]:
    # Split on headings first, then sliding windows
    sections = re.split(r"\n(?=Procedure|Note:|Warning:|Title:)", text)
    chunks: list[str] = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        if len(sec) <= chunk_size:
            chunks.append(sec)
        else:
            for i in range(0, len(sec), chunk_size):
                chunks.append(sec[i : i + chunk_size])
    return chunks or [text[:chunk_size]]


def ingest_file(stem_path: Path) -> list[Chunk]:
    """Ingest one doc stem, e.g. data/rag_docs/2011_ont_reset.pdf(.txt).

    stem_path may be .pdf, .pdf.txt, or stem without suffix.
    """
    # Resolve actual files
    name = stem_path.name
    # normalize: strip .txt if double suffix
    if name.endswith(".pdf.txt"):
        base = name[: -len(".pdf.txt")]
        pdf_path = stem_path.parent / f"{base}.pdf"
        txt_path = stem_path
    elif stem_path.suffix == ".pdf":
        pdf_path = stem_path
        txt_path = stem_path.parent / f"{stem_path.name}.txt"
        base = stem_path.stem
    else:
        base = stem_path.stem
        pdf_path = stem_path.parent / f"{base}.pdf"
        txt_path = stem_path.parent / f"{base}.pdf.txt"
        if not txt_path.exists():
            txt_path = stem_path if stem_path.exists() else None  # type: ignore

    text = _extract_text(pdf_path, txt_path) if txt_path else ""
    if not text.strip():
        return []

    meta_path = stem_path.parent / f"{base}.pdf.meta.json"
    explicit: dict = {}
    if meta_path.exists():
        try:
            explicit = json.loads(meta_path.read_text())
        except Exception:
            explicit = {}

    fm = _parse_front_matter(text)
    doc_id = explicit.get("doc_id") or fm.get("doc id") or base.upper()
    still_valid = explicit.get("still_valid_as_of") or fm.get("still valid as of")
    superseded_by = explicit.get("superseded_by") or fm.get("superseded by")
    if superseded_by and superseded_by.lower() in ("none", "-", "n/a"):
        superseded_by = None
    status = (explicit.get("status") or fm.get("status") or "").lower()
    deprecated = explicit.get("deprecated", ("deprecated" in status))

    out: list[Chunk] = []
    for i, piece in enumerate(chunk_text(text)):
        out.append(
            Chunk(
                chunk_id=f"{doc_id}-chunk{i}",
                doc_id=doc_id,
                title=explicit.get("title") or fm.get("title") or base,
                text=piece,
                source_path=str((txt_path or pdf_path)),
                created_at=explicit.get("created_at") or (still_valid or "2011-01-01"),
                still_valid_as_of=still_valid,
                superseded_by=superseded_by,
                deprecated=bool(deprecated),
                valid_until=explicit.get("valid_until"),
                tags=explicit.get("tags", []),
            )
        )
    return out


def ingest_dir(data_dir: Path | None = None) -> list[Chunk]:
    d = data_dir or DATA_DIR
    if not d.exists():
        return []
    # Collect unique stems: prefer .pdf, else .pdf.txt
    stems: dict[str, Path] = {}
    for p in sorted(d.iterdir()):
        if p.name.endswith(".pdf.txt"):
            base = p.name[: -len(".pdf.txt")]
            stems.setdefault(base, p)
        elif p.suffix == ".pdf":
            stems[p.stem] = p
    chunks: list[Chunk] = []
    for _, path in sorted(stems.items()):
        chunks.extend(ingest_file(path))
    return chunks
