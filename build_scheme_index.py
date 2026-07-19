"""Stage RAG.3 -- one-time indexer for the scheme corpus.

Reads schemes/*.md, splits each file into small chunks at heading boundaries,
embeds every chunk with OpenAI text-embedding-3-small, and persists everything
into a Chroma vector database at scheme_index/.

Run it whenever the corpus (schemes/*.md) changes:

    python build_scheme_index.py                      # incremental (add new)
    python build_scheme_index.py --reset              # wipe and rebuild from scratch
    python build_scheme_index.py --file pm_kisan.md   # index just one file
    python build_scheme_index.py --dry-run            # show chunks without embedding

Cost: about $0.0002 for all 5 docs. Embed once, query millions of times.

After indexing:
    * scheme_index/  <- persistent Chroma DB (safe to gitignore)
    * The retriever (Stage RAG.4) reads scheme_index/ and answers queries.
"""

from __future__ import annotations

# ---- SQLite compatibility shim -----------------------------------------
# Chroma requires sqlite3 >= 3.35.0. Oracle Linux 9 ships with sqlite 3.34,
# so we swap in pysqlite3-binary (bundled newer sqlite) BEFORE chromadb is
# imported. Must run first, before any other import that might touch
# sqlite3 (like langchain_chroma).
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    # If pysqlite3 isn't installed, we fall back to system sqlite3.
    # (This is OK on macOS / newer Linux distros; will error on Oracle Linux.)
    pass
# -----------------------------------------------------------------------

import argparse
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from langchain_text_splitters import (
    MarkdownHeaderTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SCHEMES_DIR    = "schemes"
PERSIST_DIR    = "scheme_index"
COLLECTION     = "agri_schemes"

# text-embedding-3-small: 1536-dim, $0.02 per 1M tokens, decent multilingual.
# If you want higher quality Hindi/Marathi: text-embedding-3-large ($0.13/M).
EMBED_MODEL    = "text-embedding-3-small"

# Chunk size cap. Our doc's ## sections are already ~200-400 tokens;
# this is a safety net for any oversized section.
CHUNK_MAX_CHARS = 2000
CHUNK_OVERLAP   = 200

# We split at Markdown headings: # (scheme title) and ## (section).
HEADERS_TO_SPLIT_ON = [
    ("#",  "scheme_name"),
    ("##", "section"),
]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------
def chunk_scheme_file(file_path: Path) -> list:
    """Split a scheme .md file into semantic chunks.

    Two-stage split:
    1. Header-aware split at `##` boundaries -> one chunk per section.
    2. Character split as a safety net for oversized sections.

    Each chunk carries metadata: scheme_name, section, source_file.
    """
    text = file_path.read_text(encoding="utf-8")

    # Stage 1: split at Markdown headings, keep headings inside chunks.
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=HEADERS_TO_SPLIT_ON,
        strip_headers=False,
    )
    header_chunks = md_splitter.split_text(text)

    # Stage 2: character-based safety net for oversized sections.
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_MAX_CHARS,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],
    )
    final_chunks = char_splitter.split_documents(header_chunks)

    # Enrich metadata with source filename.
    for c in final_chunks:
        c.metadata["source_file"] = file_path.name

    return final_chunks


# ---------------------------------------------------------------------------
# Main indexer
# ---------------------------------------------------------------------------
def build_index(reset: bool = False,
                only_file: str | None = None,
                dry_run: bool = False) -> None:
    """Build the persistent Chroma index from schemes/*.md.

    Args:
        reset:     Wipe scheme_index/ before rebuilding.
        only_file: Index just one file (e.g. 'pm_kisan.md').
        dry_run:   Show chunks without calling OpenAI (no cost).
    """
    schemes_dir = Path(SCHEMES_DIR)
    if not schemes_dir.exists():
        sys.exit(f"[error] '{SCHEMES_DIR}/' folder not found. "
                 f"Run from the project root.")

    # --- Reset the vector store if requested -------------------------------
    if reset and Path(PERSIST_DIR).exists():
        shutil.rmtree(PERSIST_DIR)
        print(f"[reset] cleared {PERSIST_DIR}/")

    # --- Discover source files --------------------------------------------
    if only_file:
        files = [schemes_dir / only_file]
        if not files[0].exists():
            sys.exit(f"[error] file not found: {files[0]}")
    else:
        files = sorted(schemes_dir.glob("*.md"))
        # Ignore the folder's own README.md if present.
        files = [f for f in files if f.name.lower() != "readme.md"]

    if not files:
        sys.exit(f"[error] no .md files found in {SCHEMES_DIR}/")

    print(f"[scan] found {len(files)} scheme file(s):")
    for f in files:
        print(f"       {f.name}")
    print()

    # --- Chunk every file --------------------------------------------------
    all_chunks = []
    for f in files:
        chunks = chunk_scheme_file(f)
        all_chunks.extend(chunks)
        print(f"[chunk] {f.name:<25} -> {len(chunks):>3} chunks")
    print(f"[chunk] total {len(all_chunks)} chunks across all files")
    print()

    # --- Dry-run: show a sample and exit ----------------------------------
    if dry_run:
        print("[dry-run] would embed the chunks and write to Chroma. "
              "Exiting without doing so.")
        print()
        print("[sample] first chunk:")
        _print_chunk(all_chunks[0])
        print()
        print("[sample] middle chunk:")
        _print_chunk(all_chunks[len(all_chunks) // 2])
        return

    # --- Embed + persist ---------------------------------------------------
    print(f"[embed] using model: {EMBED_MODEL}")
    print(f"[store] persisting to: {PERSIST_DIR}/ (collection={COLLECTION})")

    embeddings = OpenAIEmbeddings(model=EMBED_MODEL)

    Chroma.from_documents(
        documents=all_chunks,
        embedding=embeddings,
        collection_name=COLLECTION,
        persist_directory=PERSIST_DIR,
    )

    print()
    print(f"[done] indexed {len(all_chunks)} chunks from {len(files)} scheme(s)")
    print(f"[done] vector store size on disk:")
    _print_dir_size(Path(PERSIST_DIR))
    print()
    print("[sample] first chunk that got embedded:")
    _print_chunk(all_chunks[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _print_chunk(chunk) -> None:
    """Pretty-print a chunk for visual inspection."""
    print(f"   metadata: {chunk.metadata}")
    body = chunk.page_content.strip().replace("\n", "\n            ")
    if len(body) > 400:
        body = body[:400] + " ..."
    print(f"   content:  {body}")


def _print_dir_size(path: Path) -> None:
    if not path.exists():
        print(f"   (not created)")
        return
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    kb = total / 1024
    if kb < 1024:
        print(f"   {kb:.1f} KB in {path}/")
    else:
        print(f"   {kb/1024:.2f} MB in {path}/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build the Agri-Agent scheme RAG index.",
    )
    parser.add_argument("--reset", action="store_true",
                        help="Wipe scheme_index/ before rebuilding (default: add to existing).")
    parser.add_argument("--file", default=None,
                        help="Index just one scheme file (e.g. pm_kisan.md).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show chunk stats without embedding or writing.")
    args = parser.parse_args()

    build_index(reset=args.reset, only_file=args.file, dry_run=args.dry_run)
