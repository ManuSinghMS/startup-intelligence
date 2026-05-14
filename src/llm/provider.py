"""
LLM provider abstraction — supports OpenAI, GitHub Copilot (via proxy), and Groq.

Configuration:
    LLM_PROVIDER=groq (default) or openai or copilot
    GROQ_API_KEY=gsk_...            (for groq)
    OPENAI_API_KEY=sk-...           (for openai)
    COPILOT_API_URL=http://localhost:4141/v1  (for copilot)
    GITHUB_TOKEN=ghp_...

Also exports a shared async token-bucket throttle so multiple call sites
(classifier + relevance verifier) stay within the provider's rate limit
collectively, not each on their own.
"""
import asyncio
import os
import re
import time
from typing import Optional


def get_provider() -> str:
    """Get the configured LLM provider."""
    return os.getenv("LLM_PROVIDER", "groq").lower()


def get_llm_client():
    """
    Get an AsyncOpenAI client configured for the active provider.
    All three providers expose OpenAI-compatible APIs.
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
    key = os.getenv("OPENAI_API_KEY", "")
    return bool(key) and key != "sk-your-key-here"


# ---------------------------------------------------------------------------
# Token-bucket throttle
# ---------------------------------------------------------------------------
#
# Groq's free tier caps llama-3.1-8b-instant at ~6000 tokens per minute. The
# classifier and the relevance verifier BOTH hit the same key, so a naive
# pipeline blows the limit fast. Every Groq call goes through `await
# throttle_for_tokens(n)` first; if there are not enough tokens left in the
# current minute window, the call sleeps until the window refills.
#
# We default to a conservative budget below the provider cap to leave
# headroom for retries.

_GROQ_TPM = int(os.getenv("GROQ_TPM_LIMIT", "5000"))   # tokens per 60s window
_window_started_at: float = 0.0
_tokens_used_in_window: int = 0
_throttle_lock: Optional[asyncio.Lock] = None


def _get_lock() -> asyncio.Lock:
    global _throttle_lock
    if _throttle_lock is None:
        _throttle_lock = asyncio.Lock()
    return _throttle_lock


async def throttle_for_tokens(estimated_tokens: int) -> None:
    """
    Reserve `estimated_tokens` against the current minute window before
    making an LLM call. Sleeps if the budget is exhausted; otherwise
    returns immediately.

    No-op for non-Groq providers (their limits are usually loose enough
    that we do not need this).
    """
    if get_provider() != "groq":
        return

    global _window_started_at, _tokens_used_in_window
    async with _get_lock():
        now = time.monotonic()
        if now - _window_started_at >= 60.0:
            _window_started_at = now
            _tokens_used_in_window = 0

        if _tokens_used_in_window + estimated_tokens > _GROQ_TPM:
            wait = max(0.0, 60.0 - (now - _window_started_at)) + 0.5
            print(
                f"[Throttle] Groq TPM cap near ({_tokens_used_in_window}+{estimated_tokens}>{_GROQ_TPM}); "
                f"sleeping {wait:.1f}s",
                flush=True,
            )
            await asyncio.sleep(wait)
            _window_started_at = time.monotonic()
            _tokens_used_in_window = 0

        _tokens_used_in_window += estimated_tokens


_RETRY_AFTER_RE = re.compile(r"try again in ([0-9.]+)s", re.IGNORECASE)


async def call_with_retry(coro_factory, estimated_tokens: int, attempts: int = 3):
    """
    Run an LLM call (via the supplied coro factory) with token-aware
    throttling and 429 retry. `coro_factory` is a zero-arg callable that
    returns a fresh coroutine each call (we cannot await the same coro
    twice).
    """
    last_err: Optional[Exception] = None
    for i in range(attempts):
        await throttle_for_tokens(estimated_tokens)
        try:
            return await coro_factory()
        except Exception as e:
            last_err = e
            msg = str(e).lower()
            if "rate" not in msg and "429" not in msg and "tokens per minute" not in msg:
                raise
            # Try to parse the "try again in Xs" hint from the error body.
            m = _RETRY_AFTER_RE.search(str(e))
            wait = float(m.group(1)) + 1.0 if m else (2 ** i) * 2.0
            print(f"[Throttle] 429 from provider; retry {i+1}/{attempts} after {wait:.1f}s", flush=True)
            await asyncio.sleep(wait)
    if last_err:
        raise last_err
