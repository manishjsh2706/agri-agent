@echo off
cd /d D:\GenAI\Agriculture_Agent
if not exist logs mkdir logs
echo. >> logs\fetch.log
echo === Run at %DATE% %TIME% === >> logs\fetch.log
call .venv\Scripts\activate.bat
python fetch_mandi_prices.py >> logs\fetch.log 2>&1