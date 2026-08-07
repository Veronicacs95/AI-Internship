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


---

# Common Beginner Mistakes & Troubleshooting

### 1. `ModuleNotFoundError`

Your virtual environment is probably not activated.

Activate it first:

```bash
source .venv/bin/activate
```

You should see:

```text
(.venv) (base) your-name@computer week-1 %
```

---

### 2. `Error loading ASGI app`

Usually one of these:

- Wrong filename

```bash
uvicorn serve_stage1:app
```

instead of

```bash
uvicorn server_stage1:app
```

- Wrong working directory
- `main.py` cannot be found

Check where you are:

```bash
pwd
```

and list your files:

```bash
ls
```

---

### 3. `Address already in use`

Port `8000` is already occupied.

Either:

- Stop the previous server (`Ctrl + C`)

or

Run another port:

```bash
uvicorn main:app --port 8001 --reload
```

---

### 4. Why do I need multiple terminals?

A common setup is:

**Terminal 1**

Runs the FastAPI server.

```bash
uvicorn main:app --reload
```

**Terminal 2**

Sends requests.

Example:

```bash
curl ...
```

or

```bash
python test_stage1_client.py
```

The client and server are independent programs communicating over HTTP.

---

### 5. Why doesn't my client import FastAPI?

Your client communicates through HTTP.

Example:

```python
httpx.post(
    "http://127.0.0.1:8000/ask",
    json={"question": "What is RAG?"}
)
```

It talks to the server through its URL, not by importing the FastAPI application.

---

### 6. Nothing happens when I run my Python file

Most likely:

- The file is empty.
- The server is not running.
- You forgot to save the file.

Check:

```bash
python test_stage1_client.py
```

---

### 7. Why does `/` return 404?

This project only defines:

```
POST /ask
```

There is no route for:

```
GET /
```

The interactive documentation is available at:

```
http://127.0.0.1:8000/docs
```

---

### 8. 422 Unprocessable Entity

FastAPI/Pydantic rejected the request before calling the LLM.

Example:

```json
{
    "model": 123
}
```

Expected:

```json
{
    "model": "gpt-4o-mini"
}
```

No OpenAI request is made, so no tokens are spent.

---

### 9. 500 Internal Server Error

Usually means the request reached the application but something unexpected failed.

For example:

```json
{
    "model": "banana-model"
}
```

Pydantic accepts it because it is a string, but OpenAI rejects the model name.

---

### 10. 502 Bad Gateway

In Stage 3+, this is intentionally returned when the model fails schema validation even after the retry.

The application refuses to return malformed structured data.

---

### 11. Why does `force_bad=true` still return a valid answer?

This is intentional.

Flow:

```
Attempt 1
↓

Unsafe call

↓

Validation fails

↓

Retry

↓

Structured call

↓

Valid answer
```

The retry is automatic.

---

### 12. Why are the reported tokens and cost lower than expected when using `force_bad`?

The failed attempt still sends a request to OpenAI.

However, the code only reports the successful retry.

Therefore:

- actual tokens > reported tokens
- actual latency > reported latency
- actual cost > reported cost

A production application would usually accumulate usage across all attempts.

---

### 13. Why does an empty model still work?

Python uses:

```python
model = body.model or DEFAULT_MODEL
```

If:

```python
model = ""
```

Python treats an empty string as False and automatically falls back to:

```python
DEFAULT_MODEL
```

---

### 14. Why does Pydantic sometimes stop bad requests before OpenAI?

There are two validation stages.

**Before OpenAI**

Pydantic validates the incoming request.

Example:

```json
{
    "model": 123
}
```

↓

422

↓

No API call.

**After OpenAI**

Pydantic validates the model's structured response.

Example:

```
confidence = "very high"
```

↓

ValidationError

↓

Retry

↓

(or 502 if all retries fail)

---

### 15. Why doesn't the retry stop the program?

The retry works because the validation error is caught.

```python
except (ValidationError, ValueError):
    continue
```

`continue` starts the next iteration of the loop.

Without the `try/except`, Python would immediately stop executing the request.

---

### 16. Why is `.env` not uploaded to GitHub?

`.env` contains secrets.

It is ignored by Git through `.gitignore`.

Instead, commit:

```
.env.example
```

which only shows the required variables:

```text
OPENAI_API_KEY=
```

---

### 17. How does Render know my API key?

Render stores secrets as Environment Variables.

Your code simply calls:

```python
client = OpenAI()
```

The SDK automatically reads:

```
OPENAI_API_KEY
```

from the environment.

No code changes are required between local development and production.

---

### 18. What is the difference between the three validation layers?

```
Client
   │
   ▼
FastAPI
   │
   ▼
Pydantic
(validates request)
   │
   ▼
OpenAI
(generates response)
   │
   ▼
Pydantic
(validates response)
   │
   ▼
FastAPI
returns JSON
```

Each layer has a different responsibility:

- **FastAPI** → HTTP routing
- **Pydantic** → data validation
- **OpenAI** → language model generation

---

### 19. Git workflow

Typical workflow while developing:

```bash
git status
git add .
git commit -m "Describe your changes"
git push
```

Status letters:

| Letter | Meaning |
|--------|---------|
| `??` | Untracked file |
| `A` | Added (staged) |
| `M` | Modified |
| `D` | Deleted |
| `U` | Merge conflict |

---

### 20. Typical development workflow

```
Edit code
      ↓
Save file
      ↓
Uvicorn reloads automatically
      ↓
Send request with curl or Python client
      ↓
Inspect terminal logs
      ↓
Repeat
```
