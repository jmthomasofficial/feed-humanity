"""
llm_client.py — Multi-provider LLM client with round-robin key rotation.

Supports:
  - Google Gemini (free tier, 6 keys)
  - NVIDIA NIM (OpenAI-compatible, 4 keys)
  - OpenRouter (OpenAI-compatible, 1 key)

Fallback chain: Gemini → NIM → OpenRouter
Each provider rotates keys on each call to distribute load.
Keys loaded from d:\\JM\\env\\ text files (one key per line).
"""

import json
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests


# ─── Key Storage ───────────────────────────────────────────────

ENV_DIR = Path(os.environ.get("FEED_HUMANITY_ENV_DIR", r"d:\JM\env"))

def _load_keys(filename: str) -> list[str]:
    """Load API keys from a text file (one key per line)."""
    filepath = ENV_DIR / filename
    if not filepath.exists():
        return []
    keys = [
        line.strip()
        for line in filepath.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return keys


# ─── Provider Configs ──────────────────────────────────────────

@dataclass
class ProviderConfig:
    name: str
    keys: list[str]
    base_url: str
    model: str
    max_tokens: int = 2048
    timeout: int = 45
    _call_index: int = field(default=0, repr=False)

    def next_key(self) -> Optional[str]:
        """Round-robin key selection."""
        if not self.keys:
            return None
        key = self.keys[self._call_index % len(self.keys)]
        self._call_index += 1
        return key

    @property
    def available(self) -> bool:
        return len(self.keys) > 0


def _build_providers() -> list[ProviderConfig]:
    """Build provider chain in preferred fallback order."""
    providers = []

    gemini_keys = _load_keys("gemini.txt")
    if gemini_keys:
        providers.append(ProviderConfig(
            name="gemini",
            keys=gemini_keys,
            base_url="https://generativelanguage.googleapis.com/v1beta",
            model="gemini-3-flash-preview",
        ))

    nim_keys = _load_keys("nim.txt")
    if nim_keys:
        providers.append(ProviderConfig(
            name="nim",
            keys=nim_keys,
            base_url="https://integrate.api.nvidia.com/v1",
            model="meta/llama-3.1-70b-instruct",
        ))

    openrouter_keys = _load_keys("open.txt")
    if openrouter_keys:
        providers.append(ProviderConfig(
            name="openrouter",
            keys=openrouter_keys,
            base_url="https://openrouter.ai/api/v1",
            model="google/gemini-3-flash:free",
        ))

    return providers


# Singleton provider chain (initialized once on module load)
_PROVIDERS: list[ProviderConfig] = _build_providers()


# ─── API Call Implementations ──────────────────────────────────

def _call_gemini(provider: ProviderConfig, system: str, user: str) -> dict:
    """Call Google Gemini generateContent API."""
    key = provider.next_key()
    url = f"{provider.base_url}/models/{provider.model}:generateContent?key={key}"

    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": user}]}
        ],
        "systemInstruction": {
            "parts": [{"text": system}]
        },
        "generationConfig": {
            "maxOutputTokens": provider.max_tokens,
            "temperature": 0.7,
        }
    }

    resp = requests.post(url, json=payload, timeout=provider.timeout)
    resp.raise_for_status()
    data = resp.json()

    # Extract text from Gemini response
    candidates = data.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {json.dumps(data)[:300]}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts)
    return {"text": text, "provider": "gemini", "model": provider.model}


def _call_openai_compatible(provider: ProviderConfig, system: str, user: str) -> dict:
    """Call OpenAI-compatible chat/completions endpoint (NIM, OpenRouter)."""
    key = provider.next_key()
    url = f"{provider.base_url}/chat/completions"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    # OpenRouter requires extra headers
    if provider.name == "openrouter":
        headers["HTTP-Referer"] = "https://feedhumanity.org"
        headers["X-Title"] = "Feed Humanity AI Playbook"

    payload = {
        "model": provider.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": provider.max_tokens,
        "temperature": 0.7,
    }

    resp = requests.post(url, json=payload, headers=headers, timeout=provider.timeout)
    resp.raise_for_status()
    data = resp.json()

    text = data["choices"][0]["message"]["content"]
    return {"text": text, "provider": provider.name, "model": provider.model}


# ─── Main Entry Point ─────────────────────────────────────────

def chat(system_prompt: str, user_prompt: str) -> dict:
    """
    Send a chat completion request with automatic provider rotation and fallback.

    Returns:
        {
            "text": str,       # The LLM response text
            "provider": str,   # Which provider responded (gemini/nim/openrouter)
            "model": str,      # Which model was used
        }

    Raises:
        RuntimeError: If ALL providers fail.
    """
    if not _PROVIDERS:
        raise RuntimeError(
            "No API keys found. Place key files (gemini.txt, nim.txt, open.txt) "
            f"in {ENV_DIR} with one key per line."
        )

    errors = []

    for provider in _PROVIDERS:
        try:
            if provider.name == "gemini":
                return _call_gemini(provider, system_prompt, user_prompt)
            else:
                return _call_openai_compatible(provider, system_prompt, user_prompt)

        except Exception as e:
            error_msg = f"{provider.name} ({provider.model}): {e}"
            errors.append(error_msg)
            # If this key failed, try the next key on same provider once
            try:
                if len(provider.keys) > 1:
                    if provider.name == "gemini":
                        return _call_gemini(provider, system_prompt, user_prompt)
                    else:
                        return _call_openai_compatible(provider, system_prompt, user_prompt)
            except Exception as e2:
                errors.append(f"{provider.name} (retry): {e2}")
            continue

    raise RuntimeError(
        f"All providers failed. Errors:\n" +
        "\n".join(f"  - {e}" for e in errors)
    )


def list_available_providers() -> list[dict]:
    """List available providers and their key counts."""
    return [
        {
            "name": p.name,
            "model": p.model,
            "keys": len(p.keys),
            "available": p.available,
        }
        for p in _PROVIDERS
    ]


# ─── Quick Self-Test ───────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("  LLM CLIENT — Provider Status")
    print("=" * 60)

    providers = list_available_providers()
    if not providers:
        print("  NO PROVIDERS AVAILABLE")
        print(f"  Place key files in: {ENV_DIR}")
    else:
        for p in providers:
            status = "✓" if p["available"] else "✗"
            print(f"  {status} {p['name']:12s} | model={p['model']} | keys={p['keys']}")

    print()
    print("  Testing with a simple prompt...")
    try:
        result = chat(
            system_prompt="You are a helpful assistant. Respond in exactly one sentence.",
            user_prompt="What is 2+2?"
        )
        print(f"  Provider: {result['provider']}")
        print(f"  Model:    {result['model']}")
        print(f"  Response: {result['text'].strip()[:200]}")
        print()
        print("  RESULT: PASS")
    except Exception as e:
        print(f"  ERROR: {e}")
        print()
        print("  RESULT: FAIL")

    print("=" * 60)
