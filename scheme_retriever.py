"""Stage RAG.4 -- retriever wrapper around the persisted Chroma vector store.

Loads the persisted Chroma collection built by build_scheme_index.py and
exposes a simple function that Stage RAG.5 (the LangChain tool) will call.

Public API
----------
    get_relevant_scheme_chunks(query: str, k: int = 3) -> list[dict]
        Returns the top-k most relevant chunks for a query with metadata.

Usage as a script (smoke test)
------------------------------
    python scheme_retriever.py                          # runs all built-in tests
    python scheme_retriever.py "your query here"        # ad-hoc single query

The smoke test proves that semantic search works: a question phrased in
Hindi should still retrieve English chunks about the same topic, and a
question phrased with weird wording should still find the right section.
"""

from __future__ import annotations

# ---- SQLite compatibility shim (must run FIRST) -----------------------
# Chroma requires sqlite3 >= 3.35.0; Oracle Linux 9 ships sqlite 3.34.
# pysqlite3-binary bundles a modern sqlite3 which we swap in here.
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass
# -----------------------------------------------------------------------

import sys
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

from langchain_openai import OpenAIEmbeddings
from langchain_chroma import Chroma


# ---------------------------------------------------------------------------
# Configuration -- MUST match what build_scheme_index.py used.
# ---------------------------------------------------------------------------
PERSIST_DIR = "scheme_index"
COLLECTION  = "agri_schemes"
EMBED_MODEL = "text-embedding-3-small"


# ---------------------------------------------------------------------------
# Singleton for the Chroma vector store
# ---------------------------------------------------------------------------
# Loading Chroma is not instant; we want to do it ONCE per process.
# The LangGraph agent process will keep this alive between farmer queries.
_vector_store: Optional[Chroma] = None


def _get_vector_store() -> Chroma:
    """Lazy-load the persisted Chroma vector store."""
    global _vector_store
    if _vector_store is None:
        embeddings = OpenAIEmbeddings(model=EMBED_MODEL)
        _vector_store = Chroma(
            collection_name=COLLECTION,
            embedding_function=embeddings,
            persist_directory=PERSIST_DIR,
        )
    return _vector_store


# ---------------------------------------------------------------------------
# Public retrieval function
# ---------------------------------------------------------------------------
def get_relevant_scheme_chunks(query: str, k: int = 3) -> list[dict]:
    """Return the top-k most relevant chunks for a farmer's question.

    Args:
        query: farmer's question in English / Hindi / Marathi
        k:     number of chunks to return (typically 3)

    Returns:
        List of dicts:
        [
            {
                "content":          "chunk text ...",
                "scheme_name":      "PM-Kisan (Pradhan Mantri...)",
                "section":          "Benefit Amount",
                "source_file":      "pm_kisan.md",
                "similarity_score": 0.87,   # 0..1, higher = better
                "distance":         0.15,   # raw L2 distance from Chroma
            },
            ...
        ]

    An empty list is returned if the query is empty or the store has
    no data (i.e. the indexer wasn't run yet).
    """
    if not query or not query.strip():
        return []

    vs = _get_vector_store()

    # similarity_search_with_score returns (Document, distance) pairs.
    # Chroma default distance is L2 (Euclidean) -- smaller = more similar.
    try:
        results = vs.similarity_search_with_score(query.strip(), k=k)
    except Exception as e:
        print(f"[retriever] error querying vector store: {e}", file=sys.stderr)
        return []

    out = []
    for doc, distance in results:
        # Cheap sanity-friendly similarity: 1 / (1 + distance)
        # ranges (0, 1]; higher = more similar.
        similarity = 1.0 / (1.0 + float(distance))
        out.append({
            "content":          doc.page_content,
            "scheme_name":      doc.metadata.get("scheme_name", ""),
            "section":          doc.metadata.get("section", ""),
            "source_file":      doc.metadata.get("source_file", ""),
            "similarity_score": round(similarity, 3),
            "distance":         round(float(distance), 4),
        })
    return out


# ---------------------------------------------------------------------------
# Smoke tests
# ---------------------------------------------------------------------------
# These queries exercise different angles: exact terminology, informal
# phrasing, cross-language search, follow-up-style questions, etc.
TEST_QUERIES: list[str] = [
    # Straight factual English queries
    "How much money will I get from PM-Kisan?",
    "What is the interest rate on a Kisan Credit Card?",
    "Which crops are covered under MSP?",
    # Eligibility-style queries
    "Am I eligible for crop insurance if I own only 1 acre?",
    "Can tenant farmers apply for KCC?",
    # Process / how-to queries
    "How do I check my PM-Kisan payment status?",
    "How to report crop loss under PMFBY?",
    # Cross-language (retrieves English chunks despite Hindi/Marathi query)
    "PM Kisan me kitne paise milte hain?",
    "PM-Kisan साठी कोण अर्ज करू शकतो?",
    # Ambiguous / general
    "What is Soil Health Card?",
]


def _pretty_print_result(query: str, chunks: list[dict]) -> None:
    """Console printout of one query and its retrieved chunks."""
    print()
    print("=" * 78)
    print(f"QUERY: {query}")
    print("=" * 78)
    if not chunks:
        print("  (no chunks retrieved)")
        return
    for i, c in enumerate(chunks, 1):
        print(f"\n  [{i}] scheme:  {c['scheme_name'][:60]}")
        print(f"      section: {c['section']}")
        print(f"      source:  {c['source_file']}    "
              f"score: {c['similarity_score']}    dist: {c['distance']}")
        preview = c["content"].strip().replace("\n", " ")
        if len(preview) > 220:
            preview = preview[:220] + " ..."
        print(f"      text:    {preview}")


def _run_smoke_tests() -> None:
    print(f"Running {len(TEST_QUERIES)} smoke-test queries against RAG index...")
    print(f"Persist dir: {PERSIST_DIR}/  |  Model: {EMBED_MODEL}")
    for q in TEST_QUERIES:
        chunks = get_relevant_scheme_chunks(q, k=3)
        _pretty_print_result(q, chunks)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Ad-hoc query passed on command line
        user_query = " ".join(sys.argv[1:])
        result_chunks = get_relevant_scheme_chunks(user_query, k=3)
        _pretty_print_result(user_query, result_chunks)
    else:
        _run_smoke_tests()
