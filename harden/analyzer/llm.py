"""Shared LLM utilities for analyzers and AI enhancement.

llm_classify() — curl-based, returns parsed JSON array (no SDK dependency).
llm_generate() — Anthropic SDK-based, returns raw text (requires 'ai' extra).

Both gracefully degrade on missing API key or any failure.
"""

import json
import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

MODEL_MAP = {
    "haiku": "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-5-20250929",
    "opus": "claude-opus-4-6",
}


def llm_classify(prompt: str, max_tokens: int = 1024, timeout: int = 20) -> list:
    """Send a prompt to Claude Haiku and parse the JSON array response.

    Args:
        prompt: The full prompt text.  Must instruct the model to return
                a JSON array.
        max_tokens: Max response tokens.
        timeout: Request timeout in seconds.

    Returns:
        A list of dicts parsed from the model's JSON response.
        Returns [] on any failure (no API key, network error, parse error).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("No ANTHROPIC_API_KEY — skipping LLM classification")
        return []

    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    })

    try:
        result = subprocess.run(
            [
                "curl", "-s", "-m", str(timeout),
                "https://api.anthropic.com/v1/messages",
                "-H", "content-type: application/json",
                "-H", f"x-api-key: {api_key}",
                "-H", "anthropic-version: 2023-06-01",
                "-d", payload,
            ],
            capture_output=True, text=True, timeout=timeout + 5,
        )
        if result.returncode != 0:
            logger.debug("LLM curl failed: %s", result.stderr[:200])
            return []

        resp = json.loads(result.stdout)

        # Check for API errors
        if "error" in resp:
            logger.debug("LLM API error: %s", resp["error"].get("message", ""))
            return []

        text = resp.get("content", [{}])[0].get("text", "")
        return _parse_json_array(text)

    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, IndexError) as e:
        logger.debug("LLM classification failed: %s", e)
        return []


def _parse_json_array(text: str) -> list:
    """Parse a JSON array from model output, handling markdown fences."""
    text = text.strip()

    # Strip markdown code fences
    if text.startswith("```"):
        text = re.sub(r'^```\w*\n?', '', text)
        text = re.sub(r'\n?```$', '', text)
        text = text.strip()

    items = json.loads(text)
    if not isinstance(items, list):
        return []
    return items


def llm_generate(
    prompt: str,
    model: str = "claude-sonnet-4-5-20250929",
    max_tokens: int = 16384,
    timeout: int = 120,
) -> str:
    """Send a prompt to Claude and return the raw text response.

    Uses the Anthropic Python SDK (requires the 'ai' optional dependency).

    Args:
        prompt: The full prompt text.
        model: Model ID or short name (haiku/sonnet/opus).
        max_tokens: Max response tokens.
        timeout: Request timeout in seconds.

    Returns:
        The model's text response, or "" on any failure.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        logger.debug("No ANTHROPIC_API_KEY — skipping LLM generation")
        return ""

    # Resolve short names
    model_id = MODEL_MAP.get(model, model)

    try:
        import anthropic
    except ImportError:
        logger.debug("anthropic package not installed — run: pip install 'harden[ai]'")
        return ""

    try:
        client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
        response = client.messages.create(
            model=model_id,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
    except Exception as e:
        logger.debug("LLM generation failed: %s", e)
        return ""
