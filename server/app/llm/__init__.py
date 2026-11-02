"""LLM provider seam (F5, D5).

Everything that needs a model calls `get_llm()`; nothing else in the codebase
imports a concrete provider, so swapping mock -> a real provider is a
one-line config change plus one new class. See docs/03-design-decisions (D5).
"""

from functools import lru_cache

from ..config import settings
from .base import ChatContext, LLMProvider
from .mock import MockLLMProvider

__all__ = ["ChatContext", "LLMProvider", "MockLLMProvider", "get_llm"]


@lru_cache
def get_llm() -> LLMProvider:
    """Return the configured provider (LLM_PROVIDER env var)."""
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return MockLLMProvider()
    raise RuntimeError(f"Unknown LLM_PROVIDER '{provider}' (expected: mock)")
