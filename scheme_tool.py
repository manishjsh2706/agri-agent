"""Stage RAG.5 -- LangChain tool wrapping the RAG retriever + grounded LLM.

This is the tool that the LangGraph agent will call whenever the farmer
asks a question about a government scheme (PM-Kisan, PMFBY, KCC, MSP,
Soil Health Card).

Data flow:

    farmer question
        -> get_relevant_scheme_chunks()          (Stage RAG.4)
        -> confidence gate (best score >= 0.35?)
        -> if no       -> return "I don't have that info"
        -> if yes      -> build grounded prompt with the chunks
                       -> call OpenAI GPT-4o-mini
                       -> return grounded answer

Anti-hallucination design:
    1. Confidence gate before LLM call (saves cost + prevents guess).
    2. Strict system prompt: "Use ONLY the context. Never invent facts."
    3. Multi-language: answer in whatever language the farmer used.
    4. Cite source (scheme name + section) so farmer can verify.

Usage:
    from scheme_tool import lookup_scheme_info_tool
    answer = lookup_scheme_info_tool.invoke({"question": "PM-Kisan me kitne paise?"})

Smoke test:
    python scheme_tool.py                     # runs sample queries
    python scheme_tool.py "your question"     # ad-hoc query
"""

from __future__ import annotations

# ---- SQLite compatibility shim (must be first, before scheme_retriever) ---
try:
    __import__("pysqlite3")
    import sys as _sys
    _sys.modules["sqlite3"] = _sys.modules.pop("pysqlite3")
except ImportError:
    pass
# --------------------------------------------------------------------------

import os
import sys

from dotenv import load_dotenv
load_dotenv()

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from scheme_retriever import get_relevant_scheme_chunks


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Number of chunks to retrieve. 4 gives us diverse context without bloat.
TOP_K = 4

# Confidence gate. If best retrieved chunk has similarity below this,
# we assume the corpus doesn't cover the question and refuse to answer
# rather than let the LLM guess. Tune based on real queries.
MIN_SIMILARITY = 0.35

# LLM model. Kept small for cost + latency. Answers here are short and
# factual so gpt-4o-mini is more than enough.
LLM_MODEL = os.environ.get("AGRI_SCHEME_MODEL", "gpt-4o-mini")

# System prompt for grounded synthesis. Every line here prevents a
# specific failure mode I've seen in production LLM apps.
SYSTEM_PROMPT = """You are a helpful advisor for small-scale Indian farmers, \
specialising in Central Government agricultural schemes.

You will receive:
  1. A farmer's question.
  2. A CONTEXT section with 3-5 excerpts from official scheme documents.

Your job: answer the farmer's question using ONLY the CONTEXT below.

STRICT RULES:
1. Use ONLY facts from the CONTEXT. NEVER add information from your own \
knowledge, even if you are confident.
2. If the CONTEXT does not contain a clear answer, say plainly: \
"I don't have that specific detail. Please check the official website for the \
scheme" (adapt the wording to the farmer's language).
3. Keep the answer SHORT and PRACTICAL. Aim for 3-5 sentences, farmer-friendly.
4. At the end, cite your source like: "(Source: PM-Kisan / Benefit Amount)".
5. NEVER invent phone numbers, deadlines, amounts, or website URLs. If a \
number isn't in the context, don't mention one.
6. Answer in the SAME language as the farmer's question:
   - English question -> answer in English
   - Hindi question -> answer in Hindi (Devanagari)
   - Marathi question -> answer in Marathi (Devanagari)
   - Hinglish / mixed -> answer in whichever language the farmer used more
7. Use farmer-friendly words. Say "Rs 6,000 per year" not "INR 6000 per annum".
8. NEVER pretend to know something you don't. It is better to say "I don't know" \
than to guess.

Return ONLY the answer. No headings, no JSON, no meta-commentary.
"""


# ---------------------------------------------------------------------------
# Core function (business logic; testable without LangChain @tool wrapping)
# ---------------------------------------------------------------------------
def _lookup_scheme_info(question: str) -> str:
    """Core RAG lookup: retrieve chunks, apply confidence gate, call LLM.

    Returns a grounded natural-language answer OR a polite refusal.
    """
    q = (question or "").strip()
    if not q:
        return "Please ask a specific question about a government scheme " \
               "(for example: 'How much money does PM-Kisan give?')."

    # --- Retrieve ---------------------------------------------------------
    chunks = get_relevant_scheme_chunks(q, k=TOP_K)

    if not chunks:
        return ("I don't have information on that scheme yet. Please check "
                "the official Ministry of Agriculture website.")

    # --- Confidence gate --------------------------------------------------
    best = chunks[0].get("similarity_score", 0.0)
    if best < MIN_SIMILARITY:
        return ("I don't have specific information about that. Please contact "
                "your local Taluka Agriculture Officer or check the official "
                "scheme website for accurate details.")

    # --- Build the CONTEXT block for the LLM ------------------------------
    context_blocks = []
    for i, c in enumerate(chunks, 1):
        header = (f"[Chunk {i} | Source: {c['source_file']} | "
                  f"Scheme: {c['scheme_name']} | Section: {c['section']}]")
        context_blocks.append(f"{header}\n{c['content'].strip()}")
    context_text = "\n\n---\n\n".join(context_blocks)

    # --- Call the LLM -----------------------------------------------------
    llm = ChatOpenAI(model=LLM_MODEL, temperature=0.2)
    resp = llm.invoke([
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=(
            f"CONTEXT:\n\n{context_text}\n\n"
            f"---\n\n"
            f"FARMER'S QUESTION: {q}\n\n"
            f"Answer using ONLY the CONTEXT above."
        )),
    ])
    return (resp.content or "").strip()


# ---------------------------------------------------------------------------
# LangChain @tool wrapper (this is what the agent will call)
# ---------------------------------------------------------------------------
@tool
def lookup_scheme_info_tool(question: str) -> str:
    """Look up information about a Central Government agricultural scheme.

    Use this tool whenever the farmer asks about ANY of these schemes:
    - PM-Kisan (income support, Rs 6000/year)
    - PMFBY (crop insurance)
    - KCC (Kisan Credit Card / short-term credit)
    - MSP (Minimum Support Price)
    - Soil Health Card

    Also use for related questions about eligibility, application process,
    required documents, benefit amounts, or how to check status/claim.

    Args:
        question: The farmer's question, exactly as they asked it (English,
                  Hindi, or Marathi). Don't paraphrase.

    Returns:
        A grounded natural-language answer citing the scheme source.
        If the scheme corpus doesn't cover the topic, returns a polite refusal.
    """
    return _lookup_scheme_info(question)


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------
TEST_QUERIES: list[str] = [
    # English factual
    "How much money will I get from PM-Kisan?",
    "What is the interest rate on KCC?",
    "Which crops are covered under MSP?",
    # Eligibility
    "Am I eligible for PM-Kisan if I paid income tax last year?",
    "Can a tenant farmer apply for KCC?",
    # Process / how-to
    "How do I report a crop loss under PMFBY?",
    "How do I get my soil tested for free?",
    # Cross-language
    "PM Kisan me kitne paise milte hain?",           # Hindi (Roman)
    "PM-Kisan साठी कोण अर्ज करू शकतो?",              # Marathi (Devanagari)
    # Out-of-scope (should say "I don't have that info")
    "What is the price of onion at Pune mandi today?",
    "How do I get a tractor loan?",
]


def _run_smoke_tests() -> None:
    print(f"Running {len(TEST_QUERIES)} scheme-tool smoke tests...")
    print(f"Model: {LLM_MODEL}   Top-K: {TOP_K}   Min-similarity: {MIN_SIMILARITY}")
    for i, q in enumerate(TEST_QUERIES, 1):
        print()
        print("=" * 78)
        print(f"[{i}] QUERY: {q}")
        print("=" * 78)
        try:
            answer = _lookup_scheme_info(q)
        except Exception as e:
            answer = f"(error: {type(e).__name__}: {e})"
        print(answer)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Ad-hoc single query
        user_q = " ".join(sys.argv[1:])
        print(_lookup_scheme_info(user_q))
    else:
        _run_smoke_tests()
