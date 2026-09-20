import hashlib
import importlib.metadata
import os

from google import genai
from google.genai import types

KEY = os.getenv("GEMINI_API_KEY", "").strip()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

def fp(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]

def run(label, fn):
    try:
        r = fn()
        text = getattr(r, "text", None) or ""
        print(f"OK {label}: {text[:120]!r}")
    except Exception as exc:
        print(f"ERR {label}: {type(exc).__name__}: {str(exc)[:500]}")

print("SDK:", importlib.metadata.version("google-genai"))
print("KEY_PRESENT:", bool(KEY))
print("KEY_FP:", fp(KEY) if KEY else "none")
print("MODEL:", MODEL)

client_default = genai.Client(api_key=KEY)
client_explicit = genai.Client(api_key=KEY, vertexai=False)

run("plain-default", lambda: client_default.models.generate_content(
    model=MODEL, contents="قل مرحباً فقط"
))

run("plain-explicit-developer", lambda: client_explicit.models.generate_content(
    model=MODEL, contents="قل مرحباً فقط"
))

run("google-search", lambda: client_explicit.models.generate_content(
    model=MODEL,
    contents="ما هي عاصمة مصر؟",
    config=types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    ),
))

run("url-context", lambda: client_explicit.models.generate_content(
    model=MODEL,
    contents="لخص الصفحة https://ai.google.dev/",
    config=types.GenerateContentConfig(
        tools=[types.Tool(url_context=types.UrlContext())]
    ),
))

run("function-tool", lambda: client_explicit.models.generate_content(
    model=MODEL,
    contents="استخدم الأداة للعثور على 2+2",
    config=types.GenerateContentConfig(
        tools=[
            types.Tool(function_declarations=[{
                "name": "calculator",
                "description": "Calculate an arithmetic expression.",
                "parameters": {
                    "type": "object",
                    "properties": {"expression": {"type": "string"}},
                    "required": ["expression"],
                },
            }])
        ]
    ),
))
