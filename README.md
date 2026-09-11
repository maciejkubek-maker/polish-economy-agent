Autonomous Macroeconomic Agent

An autonomous analytical system powered by Large Language Models (Google Gemini and OpenAI GPT) and the Tavily Search API, designed to regularly collect, verify, aggregate, and critically evaluate macroeconomic health indicators (default: Poland).
🚀 How It Works

    Trusted Source Registry: If the database contains no sources, an LLM generates official and reputable institutions (GUS, NBP, OECD, etc.) and stores them in SQLite.

    Freshness Verification (Caching): The system checks the timestamp of the latest records. If existing indicators are less than 3 days old, redundant and costly external API calls are skipped.

    Data Retrieval: When data is outdated or missing, Tavily Search retrieves the most recent macroeconomic articles and releases. Two independent agents (GeminiAgent and GPTAgent) extract structured indicators (GDP, CPI inflation, unemployment rate, etc.).

    Evaluation and Synthesis: The evaluator examines datasets from both agents, tracks historical trends, and compiles an objective economic report.

    HTML Presentation: The finalized report is converted into report.html and served via a lightweight Flask web server.

🛠️ Requirements & Installation

    Clone the repository and navigate to the project directory:
    Bash

    git clone <repository-url>
    cd <repository-folder>

    Create and activate a virtual environment:
    Bash

    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate

    Install required packages:
    Bash

    pip install flask langchain-core langchain-google-genai langchain-openai tavily-python python-dotenv pydantic

⚙️ Environment Configuration (.env)

Create a .env file in the root directory and provide your API keys:
Fragment kodu

GOOGLE_API_KEY="your-google-gemini-key"
OPENAI_API_KEY="your-openai-key"
TAVILY_API_KEY="your-tavily-key"

Default settings (target country, LLM models) can be configured in config.py.
▶️ Usage

Run the primary application script:
Bash

python app.py

The pipeline will verify cache, retrieve fresh data if needed, generate report.html, and start the local Flask server at:
👉 [http://127.0.0.1:5000/report.html](http://127.0.0.1:5000/report.html)
📁 Project Structure

    app.py – Application orchestrator and Flask server endpoints.

    config.py – Environment variables and application defaults.

    modules/database.py – SQLite database management and cache validation.

    modules/search_service.py – Tavily Search API client wrapper.

    modules/sources.py – LLM-assisted discovery of trusted economic sources.

    modules/data_fetcher.py – Gemini-based indicator extraction agent.

    modules/gpt_fetcher.py – GPT-based indicator extraction agent.

    modules/evaluator.py – Comparative analysis engine and final report synthesizer.