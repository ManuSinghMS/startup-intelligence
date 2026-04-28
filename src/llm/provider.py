"""
LLM provider abstraction — supports OpenAI and GitHub Copilot (via proxy).

Usage:
    from src.llm.provider import get_llm_client, get_model_name

    client = get_llm_client()
    model = get_model_name()
    response = await client.chat.completions.create(
        model=model, messages=[...], ...
    )

Configuration:
    LLM_PROVIDER=openai (default) or copilot
    OPENAI_API_KEY=sk-...           (for openai provider)
    COPILOT_API_URL=http://localhost:4141/v1  (for copilot provider)
    GITHUB_TOKEN=ghp_...            (for copilot provider)
"""
import os
from typing import Optional


def get_provider() -> str:
    """Get the configured LLM provider."""
    return os.getenv("LLM_PROVIDER", "openai").lower()


def get_llm_client():
    """
    Get an AsyncOpenAI client configured for the active provider.
    Both OpenAI and Copilot proxy use OpenAI-compatible APIs.
    """
    from openai import AsyncOpenAI

    provider = get_provider()

    if provider == "copilot":
        base_url = os.getenv("COPILOT_API_URL", "http://localhost:4141/v1")
        return AsyncOpenAI(
            base_url=base_url,
            api_key=os.getenv("GITHUB_TOKEN", "copilot"),
        )

    if provider == "groq":
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            return None
        return AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=api_key,
        )

    # Default: OpenAI
    api_key = os.getenv("OPENAI_API_KEY", "")
    if not api_key or api_key == "sk-your-key-here":
        return None
    return AsyncOpenAI(api_key=api_key)


def get_model_name() -> str:
    """Get the model name to use for the active provider."""
    provider = get_provider()
    if provider == "copilot":
        return os.getenv("COPILOT_MODEL", "gpt-4o")
    if provider == "groq":
        return os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def is_configured() -> bool:
    """Check if any LLM provider is configured and usable."""
    provider = get_provider()
    if provider == "copilot":
        return bool(os.getenv("COPILOT_API_URL"))
    if provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    # OpenAI
    key = os.getenv("OPENAI_API_KEY", "")
    return bool(key) and key != "sk-your-key-here"
