import httpx

response = httpx.post(
    "http://127.0.0.1:8000/ask",
    json={"question": "What is RAG?"},
    timeout=120.0,
)

print(response.status_code)
print(response.json())