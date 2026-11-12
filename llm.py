"""Pluggable LLM for SevaAgent.

Priority:
  1. OPENAI_API_KEY  -> OpenAI Chat Completions API
  2. HF_TOKEN        -> Hugging Face Inference Providers (OpenAI-compatible)
  3. neither         -> demo mode (no LLM; the agent answers from its
                       tools + curated data + templates)

No key is ever hard-coded. Set keys as environment variables only.
"""

import os

import requests

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
HF_URL = "https://router.huggingface.co/v1/chat/completions"


def get_llm_config():
    """Return (mode, config) where mode is 'openai', 'hf' or 'demo'."""
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", {
            "api_key": os.environ["OPENAI_API_KEY"],
            "url": OPENAI_URL,
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }
    if os.environ.get("HF_TOKEN"):
        return "hf", {
            "api_key": os.environ["HF_TOKEN"],
            "url": HF_URL,
            "model": os.environ.get(
                "HF_MODEL", "meta-llama/Llama-3.1-8B-Instruct"
            ),
        }
    return "demo", {}


def llm_chat(messages, config, timeout=60):
    """One chat-completion call. Returns the reply text (raises on error)."""
    resp = requests.post(
        config["url"],
        headers={
            "Authorization": f"Bearer {config['api_key']}",
            "Content-Type": "application/json",
        },
        json={
            "model": config["model"],
            "messages": messages,
            "temperature": 0.3,
            "max_tokens": 900,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
