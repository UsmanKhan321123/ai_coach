# AI Learning Coach

A Streamlit app that helps students learn through personalized roadmaps,
guided explanations, and practice exercises — powered by Groq LLM.
It tracks progress and recommends what to focus on next, instead of just
handing over exact answers.

## Project structure

| File            | Responsibility                                                        |
|------------------|------------------------------------------------------------------------|
| `app.py`         | Main Streamlit app — navigation and page wiring                        |
| `assessment.py`  | Generates & evaluates a diagnostic quiz for a topic/difficulty         |
| `roadmap.py`     | Builds a personalized module/topic roadmap from assessment results     |
| `ai_coach.py`    | Central Groq LLM access + explanations, exercises, hints, chat         |
| `progress.py`    | JSON-based persistence, analytics, and the progress dashboard          |

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

2. Get a free API key from [console.groq.com](https://console.groq.com/keys).

3. Provide the key one of two ways:

   **Option A — environment variable**
   ```bash
   export GROQ_API_KEY="gsk_xxxxxxxxxxxxxxxx"
   ```

   **Option B — Streamlit secrets** (create `.streamlit/secrets.toml`)
   ```toml
   GROQ_API_KEY = "gsk_xxxxxxxxxxxxxxxx"
   ```

4. Run the app:
   ```bash
   streamlit run app.py
   ```

## How it works

1. **Start New Topic** — enter what you want to learn and your self-rated level.
2. **Assessment** — take a short LLM-generated diagnostic quiz.
3. **Roadmap** — a personalized module/topic plan is generated based on your
   actual strengths and weaknesses (not just what you self-reported).
4. **Coach & Practice** — get guided explanations, hands-on exercises with
   hints (not solutions), and a chat coach that nudges you toward the
   answer instead of giving it away.
5. **Progress Dashboard** — see completion %, concept mastery, practice
   accuracy, and your study streak.

Student data is stored as plain JSON files in `./data/<student_id>.json`.

## Notes / next steps

- `GROQ_MODEL` env var can override the default model
  (`openai/gpt-oss-120b`).
- Persistence is file-based for simplicity; swapping `progress.py`'s
  storage functions for a real database later won't require touching
  any other file, since `app.py` only calls its public functions.
