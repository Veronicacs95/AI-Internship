# Week 1 — `/ask` Demo (5 stages)

Build a typed LLM endpoint step by step. Each stage is a standalone FastAPI app that can be run and compared independently.

---

## Setup

Clone the repository, create a virtual environment, install the dependencies, and create your local environment file.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and add your OpenAI API key:

```text
OPENAI_API_KEY=your_api_key_here
```

> **Never commit `.env` to GitHub.** Only `.env.example` should be included in the repository.

Example `.env.example`:

```text
OPENAI_API_KEY=
```

---

## Demo stages

| Stage | File | What you learn |
|-------|------|----------------|
| 1 | `serve_stage1.py` | Bare `/ask` endpoint returning a string answer and token count |
| 2 | `serve_stage2.py` | Structured outputs using Pydantic and `completions.parse()` |
| 3 | `serve_stage3.py` | Validation guardrails with retry (`force_bad`) |
| 4 | `serve_stage4.py` | Model selection and latency measurement |
| 5 | `serve_stage5.py` / `main.py` | Complete system including cost estimation |

---

## Run locally

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Run one server at a time (all examples use port `8000`).

Stage 1

```bash
uvicorn serve_stage1:app --host 127.0.0.1 --port 8000 --reload
```

Stage 2

```bash
uvicorn serve_stage2:app --host 127.0.0.1 --port 8000 --reload
```

Stage 3

```bash
uvicorn serve_stage3:app --host 127.0.0.1 --port 8000 --reload
```

Stage 4

```bash
uvicorn serve_stage4:app --host 127.0.0.1 --port 8000 --reload
```

Stage 5 (full application)

```bash
uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

FastAPI documentation:

```
http://127.0.0.1:8000/docs
```

---

## Test with curl

Basic request:

```bash
curl -X POST http://127.0.0.1:8000/ask \
-H "Content-Type: application/json" \
-d '{"question":"What is Retrieval-Augmented Generation?"}'
```

Use a different model:

```bash
curl -X POST http://127.0.0.1:8000/ask \
-H "Content-Type: application/json" \
-d '{"question":"What is Retrieval-Augmented Generation?","model":"gpt-4o-mini"}'
```

Trigger the retry demo:

```bash
curl -X POST http://127.0.0.1:8000/ask \
-H "Content-Type: application/json" \
-d '{"question":"What is Retrieval-Augmented Generation?","force_bad":true}'
```

---

## Streamlit demo

Run the UI in another terminal while the FastAPI server is running.

```bash
streamlit run demo_page.py
```

Open:

```
http://localhost:8501
```

API URL:

```
http://127.0.0.1:8000
```

---

## Smoke test

```bash
python test_all_stages.py
```

---

## Deploy to Render

Create a new **Web Service** in Render.

Use the following settings:

**Runtime**

```
Python 3
```

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

If your repository contains multiple projects, set the **Root Directory** to the folder containing `main.py` and `requirements.txt`.

Add the following environment variable:

| Key | Value |
|-----|------|
| `OPENAI_API_KEY` | Your OpenAI API key |

> Never upload `.env` to Render. Store secrets using Render Environment Variables.

After deployment, test your public endpoint:

```bash
curl -X POST https://your-service.onrender.com/ask \
-H "Content-Type: application/json" \
-d '{"question":"What is Retrieval-Augmented Generation?"}'
```

Public API documentation:

```
https://your-service.onrender.com/docs
```

---

## Default model

The default model is **gpt-4o**, selected because it provides the highest response quality while maintaining acceptable latency for this demo. In testing, a typical request cost approximately **$0.005–$0.006 USD**.

For lower-cost deployments, **gpt-4o-mini** provided similar quality while reducing the cost to approximately **$0.00026 USD** per request.

---

## Project structure

```text
week-1/
├── main.py
├── serve_stage1.py
├── serve_stage2.py
├── serve_stage3.py
├── serve_stage4.py
├── serve_stage5.py
├── demo_page.py
├── test_all_stages.py
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Security

- Keep API keys in `.env` locally.
- Never commit `.env` to GitHub.
- Commit only `.env.example`.
- Store production secrets using Render Environment Variables.
```
