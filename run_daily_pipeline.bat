@echo off
REM ============================================================
REM  Agri-Agent daily pipeline -- run once every morning.
REM  Order matters:
REM    1) fetch_prices.py          -- pull today's mandi prices
REM    2) daily_advice.py          -- rules -> daily_advice_YYYY-MM-DD.json
REM    3) advice_writer.py         -- LLM  -> daily_messages_YYYY-MM-DD.json
REM    4) send_daily_messages.py   -- Telegram -> farmers
REM
REM  Point a Windows Task Scheduler task at THIS .bat file
REM  and set it to run daily at ~06:00.
REM ============================================================

setlocal
cd /d D:\GenAI\Agriculture_Agent

REM Activate the virtual environment (adjust path if yours differs)
call .venv\Scripts\activate.bat

REM Optional: log all output with a timestamp so you can debug
set LOGDIR=logs
if not exist %LOGDIR% mkdir %LOGDIR%
set LOGFILE=%LOGDIR%\pipeline_%DATE:~-4%-%DATE:~-10,2%-%DATE:~-7,2%.log

echo === Pipeline run at %DATE% %TIME% === >> %LOGFILE%

python fetch_prices.py         >> %LOGFILE% 2>&1
python daily_advice.py         >> %LOGFILE% 2>&1
python advice_writer.py        >> %LOGFILE% 2>&1
python send_daily_messages.py  >> %LOGFILE% 2>&1

echo === Pipeline done at %DATE% %TIME% === >> %LOGFILE%
echo. >> %LOGFILE%

endlocal
