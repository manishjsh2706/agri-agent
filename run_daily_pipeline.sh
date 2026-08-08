#!/bin/bash
# Usage: run_daily_pipeline.sh [morning|evening]
#   morning  = 11 AM run (opening prices, "act today" framing)
#   evening  = 9 PM run (closing prices, "plan for tomorrow" framing)
# Defaults to "morning" if no argument.

set -euo pipefail
cd /home/opc/agri-agent
source .venv/bin/activate
mkdir -p logs

MODE="${1:-morning}"
if [[ "${MODE}" != "morning" && "${MODE}" != "evening" ]]; then
    echo "ERROR: mode must be 'morning' or 'evening', got '${MODE}'"
    exit 1
fi

export BRIEFING_MODE="${MODE}"
STAMP=$(date +'%Y-%m-%d')
LOG="logs/pipeline_${STAMP}_${MODE}.log"

{
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') pipeline start (mode=${MODE}) ==="
    python fetch_mandi_prices.py
    python daily_advice.py
    python advice_writer.py
    python send_daily_messages.py
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') pipeline end (mode=${MODE}) ==="
    echo ""
} >> "${LOG}" 2>&1
