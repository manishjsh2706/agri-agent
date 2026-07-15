Agri-Agent
Multi-lingual AI market advisor for small-scale Indian farmers, delivered via Telegram.

Farmers in Pune district (Maharashtra) can ask Agri-Agent free-form questions in Hindi, Marathi, or English — questions like "Which mandi is best for onion today?" or "Should I sell tomato now or wait a week?" — and get an answer backed by real mandi price data, weather forecasts, and time-series price forecasting. The system also sends personalized daily briefings at 6 AM automatically.

Currently deployed on Oracle Cloud, running 24/7.


Table of Contents
Demo
What it does
Architecture
Tech Stack
How the agent avoids hallucinating
Live deployment
Local setup
Project structure
Roadmap
Author


Demo
Add 2-3 screenshots here — one of a farmer asking a question, one of a daily 6 AM briefing, one of the LangGraph agent choosing a tool. Save them under docs/screenshots/ and reference like:

![Farmer asks about onion prices](docs/screenshots/telegram_onion.png)

![Daily briefing in Marathi](docs/screenshots/daily_briefing_mr.png)


What it does
Six live use cases:

Mandi comparison — "For onion, which of Pune, Manchar, and Junnar mandis gives the best net return today after travel cost?"
Best-mandi selection — "Find the nearest mandi for tomato with an acceptable price."
Price forecasting — 7-day forecast with confidence bands, using Holt-Winters + Ridge regression + walk-forward cross-validation to auto-pick the best model per crop.
Sell-now-vs-wait — "Sell today or wait?" recommendation with expected price gain, confidence, and best-day estimate.
All crops at a specific mandi — "What crops are trading at Pune (Manjri) APMC today?"
All crops near a farmer — "What crops are being sold at mandis around me right now?"

Plus proactive daily briefings — every morning at 6 AM IST, a decision engine evaluates each farmer's stock, open sell intents, price forecasts, and weather forecast, then sends a personalized natural-language message in the farmer's preferred language (Hindi / Marathi / English).


Architecture
flowchart TB

    subgraph Telegram["Telegram (Farmer's phone)"]

        F[Farmer]

    end

    subgraph VM["Oracle Cloud VM"]

        BOT[telegram_bot.py<br/>systemd service, 24/7]

        AGENT[LangGraph Agent<br/>with conversation memory]

        TOOLS[10+ Custom Tools<br/>price lookup, forecast,<br/>weather, mandi resolver,<br/>intent tracking]

        DB[(SQLite<br/>farmers, stock,<br/>prices, intents)]

        CRON[cron @ 6 AM IST]

        PIPE[Daily Pipeline<br/>fetch_prices → advice<br/>→ writer → sender]

    end

    subgraph External["External APIs"]

        MANDI[data.gov.in<br/>mandi price API]

        WEATHER[Open-Meteo<br/>weather API]

        LLM[OpenAI<br/>GPT-4o-mini]

    end

    F <-->|chat| BOT

    BOT --> AGENT

    AGENT -->|tool calls| TOOLS

    AGENT -->|LLM| LLM

    TOOLS --> DB

    TOOLS --> MANDI

    TOOLS --> WEATHER

    CRON --> PIPE

    PIPE --> DB

    PIPE --> MANDI

    PIPE --> LLM

    PIPE -->|sendMessage| F

Two independent flows:

Reactive — farmer sends a Telegram message → LangGraph agent picks the right tools → replies in seconds.
Proactive — cron runs the pipeline every morning → generates personalized nudges → sends via Telegram.


Tech Stack
Layer
Choice
LLM
OpenAI GPT-4o-mini via langchain-openai
Agent framework
LangChain (tool definitions) + LangGraph (state machine, thread-scoped memory)
Backend
Python 3.11, FastAPI (optional web UI), SQLite
Forecasting
Holt-Winters (statsmodels), Ridge regression (scikit-learn), walk-forward CV
Data sources
data.gov.in (mandi prices), Open-Meteo (weather)
Messaging
Telegram Bot API
Infrastructure
Oracle Cloud Free Tier (Ampere ARM, Oracle Linux 9), systemd, cron, SELinux
DevOps
Git, GitHub, VS Code Remote-SSH, bash deploy scripts



How the agent avoids hallucinating
LLMs love to invent plausible-looking numbers. For a farmer relying on the price of onions to decide whether to make a 40 km trip, that is a real problem. Three techniques together give near-zero hallucination on numeric data:

Procedural system prompt (routes a, b, c, d, e). The prompt is not a persona description — it is a routing decision tree. "If the user asks type X, call tool Y FIRST, then answer using only the numbers the tool returned. Never invent a price, mandi, or distance."
Tool-boundary filters. Every tool applies staleness filters (data older than N days → return None), sanity bands (impossible values → drop), and normalization (unit consistency) BEFORE the LLM sees the numbers. Bad data never reaches the model.
Explicit hallucination guards on names. For example, find_mandi_by_name_tool returns None if the user asked for a mandi outside the Pune district database, so the LLM cannot substitute a nearby-sounding mandi it "remembers" from training.


Live deployment
Running 24/7 on Oracle Cloud Free Tier:

Compute: Ampere A1.Flex, 1 OCPU, 1 GB RAM (with 4 GB swap for OOM protection)
OS: Oracle Linux 9
Bot service managed by systemd with automatic restart on failure or reboot
Daily pipeline scheduled via cron at 0 6 * * * (IST)
Deploys via git pull on the VM, orchestrated by deploy_from_git.sh
All secrets in .env (never committed — see .gitignore)


Local setup
For development or evaluation on your own machine.

Prerequisites

Python 3.11+ (union type syntax like dict[str, int] is used throughout)
An OpenAI API key
A Telegram bot token (from @BotFather)
A data.gov.in API key (free — https://data.gov.in)

Install

git clone https://github.com/<your-username>/agri-agent.git

cd agri-agent

python3.11 -m venv .venv

source .venv/bin/activate    # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env

# open .env in your editor and fill in the three API keys

Initialize the database

python db.py                 # creates mandi_prices.db with all tables

python seed_farmers.py       # optional: seed a few demo farmer profiles

Fetch some initial data

python fetch_mandi_prices.py # pulls today's Pune-district prices

Run the Telegram bot

python telegram_bot.py

Now message your bot in Telegram: /start → /register <phone-of-a-seeded-farmer> → ask a question.

Run the daily pipeline manually

python daily_advice.py       # generate today's nudges

python advice_writer.py      # convert nudges to natural-language messages

python send_daily_messages.py # send via Telegram

Or run all four in sequence:

bash run_daily_pipeline.sh


Project structure
agri-agent/

│

├── Core data layer

│   ├── db.py                     # SQLite schema (farmers, stock, prices, intents)

│   ├── farmer_profile.py         # farmer + stock CRUD helpers

│   ├── open_intents.py           # sell-intent CRUD helpers

│   └── history_query.py          # pull price time-series from DB

│

├── Data ingestion

│   ├── fetch_mandi_prices.py     # data.gov.in → DB

│   ├── weather.py                # Open-Meteo forecast wrapper

│   ├── pune_mandis.py            # mandi lat/lon + fuzzy resolver

│   └── seed_*.py                 # test data helpers

│

├── Forecast engine

│   ├── forecast.py               # Holt-Winters + Ridge implementations

│   ├── forecast_eval.py          # walk-forward CV harness, leaderboard

│   ├── best_window.py            # sell-now-vs-wait decision logic

│   └── mock_history.py           # synthetic time-series for tests

│

├── AI agent layer

│   ├── agent_tools.py            # LangChain @tool wrappers (10+ tools)

│   ├── agent.py                  # simple stateless tool-router

│   ├── agent_memory.py           # LangGraph agent with per-user memory

│   └── comparison.py             # mandi comparison logic

│

├── Front-ends

│   ├── telegram_bot.py           # Telegram bot (production)

│   └── chat_app.py               # optional local FastAPI web UI

│

├── Daily pipeline

│   ├── daily_advice.py           # decision engine (produces nudges)

│   ├── advice_writer.py          # LLM → natural-language messages

│   ├── send_daily_messages.py    # Telegram sender

│   └── run_daily_pipeline.sh     # chains the four scripts

│

├── Deploy / ops

│   ├── requirements.txt

│   ├── .env.example

│   ├── .gitignore

│   └── DEPLOYMENT_GUIDE.md, GITHUB_SETUP_GUIDE.md, FARMER_REGISTRATION_GUIDE.md

│

└── Test / debug utilities

    ├── check_db.py, diagnose.py, verify_onion_price.py, ...


Roadmap
Planned extensions (in priority order):

RAG (Retrieval-Augmented Generation) for government schemes. Add a scheme advisor — farmers ask about PM-Kisan, crop insurance, subsidies, and the agent retrieves relevant scheme details from a curated document store using vector embeddings (FAISS / Chroma).
MCP (Model Context Protocol) server. Expose the domain toolkit (mandi lookup, forecast, weather) as an MCP server so it can be consumed by Claude Desktop, Cursor, and other MCP-compatible clients — turning the agent's tools into a reusable enterprise capability.
Multi-agent coordination. Split routing, forecasting, and messaging into specialized sub-agents that hand off tasks (LangGraph sub-graphs).
LLM observability. Integrate LangSmith / LangFuse tracing for cost tracking, latency monitoring, and prompt regression testing.
Evaluation harness. Automated tests for hallucination (does the answer cite tool-returned numbers only?), latency, and multi-lingual fidelity (Devanagari script correctness).
Preference dataset. Add farmer feedback capture ("was this useful?") to build a fine-tuning dataset for future response-quality improvements.


Author
Manish Joshi manish.jsh90@gmail.com

Built to explore production Agentic AI end-to-end — from tool design and prompt engineering through cloud infrastructure and real-user deployment.

If you are hiring for AI, LLM, or GenAI engineering roles, I'd love to talk.


License
MIT

