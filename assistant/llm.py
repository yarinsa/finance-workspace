"""Minimal OpenAI-compatible chat client, so the model is a config choice
(Ollama, LM Studio, llama.cpp, MLX server or a hosted API all speak this)."""
import json
import os
import re
import urllib.request

BASE_URL = os.environ.get("ASSISTANT_BASE_URL", "http://localhost:11434/v1")
MODEL = os.environ.get("ASSISTANT_MODEL", "qwen3:30b-a3b-instruct-2507-q4_K_M")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def strip_think(text):
    """Drop reasoning blocks some models emit even when asked not to."""
    return _THINK.sub("", text or "").strip()


def chat(messages, tools=None, base_url=None, model=None, timeout=300):
    """One chat completion; returns the assistant message dict."""
    body = {"model": model or MODEL, "messages": messages, "temperature": 0.2}
    if tools:
        body["tools"] = tools
    req = urllib.request.Request(
        f"{base_url or BASE_URL}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)["choices"][0]["message"]
