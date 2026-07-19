# Scheme Corpus for RAG

This folder contains curated scheme documents that feed the RAG-based scheme advisor tool. Every file here becomes searchable knowledge for the Agri-Agent bot.

## Rules for adding/editing scheme docs

1. **One scheme per file.** Named `<scheme_short_name>.md`.
2. **Same structure** for every file:
   - Header (title + aliases + metadata + last-verified date)
   - What it is
   - Benefit / What it provides
   - Eligibility
   - Who is NOT eligible / Exclusions
   - How to apply
   - Required documents
   - How to check status / claim procedure
   - Common issues
   - Summary card
   - Footer safety note
3. **Include aliases in every language** the farmer might use (English, Hindi, Marathi, local dialect names).
4. **Never hardcode facts you can't verify** — phone numbers, deadlines, amounts must have an official source cited.
5. **Update `Last verified` date** after every fact check.

## After editing any file

Re-run the indexer to refresh the vector store:

```bash
cd /home/opc/agri-agent
source .venv/bin/activate
python build_scheme_index.py
```

Then either:
- Nothing — the retriever reads the fresh index on next query, OR
- Restart the bot for a clean state: `sudo systemctl restart agri-agent-bot`

## Current corpus

- `pm_kisan.md` — Pradhan Mantri Kisan Samman Nidhi (income support)
- `pmfby.md` — Pradhan Mantri Fasal Bima Yojana (crop insurance)
- `kcc.md` — Kisan Credit Card (short-term credit)
- `msp.md` — Minimum Support Price (procurement policy)
- `soil_health_card.md` — Soil Health Card (soil testing + fertilizer advice)

## Future additions

Add more Central schemes here first. State-specific schemes (e.g., Maharashtra MJPSKY) will go under `schemes/state/maharashtra/` in future.
