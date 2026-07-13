#!/bin/bash
set -euo pipefail
cd /home/opc/agri-agent
source .venv/bin/activate
mkdir -p logs
STAMP=$(date +'%Y-%m-%d')
LOG="logs/pipeline_${STAMP}.log"
{
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') pipeline start ==="
    python fetch_mandi_prices.py
    python daily_advice.py
    python advice_writer.py
    python send_daily_messages.py
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') pipeline end ==="
    echo ""
} >> "${LOG}" 2>&1
