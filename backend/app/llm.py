"""LLM access behind a small interface so the platform degrades gracefully without a key."""
import asyncio
import logging
import re
from collections.abc import AsyncIterator
from typing import Protocol, TypeVar

from pydantic import BaseModel

from app.core.config import get_settings

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLM(Protocol):
    available: bool

    async def structured(self, schema: type[T], system: str, user: str) -> T: ...
    async def complete(self, system: str, user: str) -> str: ...
    def stream(self, system: str, user: str) -> AsyncIterator[str]: ...


class NullLLM:
    available = False

    async def structured(self, schema, system, user):
        raise RuntimeError("LLM not configured")

    async def complete(self, system, user):
        raise RuntimeError("LLM not configured")

    async def stream(self, system, user):
        raise RuntimeError("LLM not configured")
        yield ""  # pragma: no cover  (makes this an async generator)


_HINT = re.compile(r"try again in ([\d.]+)\s*(ms|s)", re.I)


def _rate_wait(exc: Exception) -> float | None:
    text = str(exc)
    if "429" not in text and "rate_limit" not in text:
        return None
    m = _HINT.search(text)
    if not m:
        return 5.0
    return min(float(m.group(1)) / (1000 if m.group(2).lower() == "ms" else 1) + 0.5, 20.0)


class GroqLLM:
    available = True
    _gate = asyncio.Semaphore(2)  # free-tier token-per-minute limits punish bursts

    def __init__(self) -> None:
        from langchain_groq import ChatGroq

        s = get_settings()
        self._chat = ChatGroq(model=s.llm_model, api_key=s.groq_api_key, temperature=0, timeout=s.llm_timeout_s, max_retries=1)

    async def _retry(self, fn, attempts: int = 4):
        for i in range(attempts):
            try:
                async with self._gate:
                    return await fn()
            except Exception as e:
                wait = _rate_wait(e)
                if wait is None or i == attempts - 1:
                    raise
                log.info("rate limited, retrying in %.1fs", wait)
                await asyncio.sleep(wait)

    async def structured(self, schema, system, user):
        model = self._chat.with_structured_output(schema)
        return await self._retry(lambda: model.ainvoke([("system", system), ("human", user)]))

    async def complete(self, system, user):
        r = await self._retry(lambda: self._chat.ainvoke([("system", system), ("human", user)]))
        return str(r.content).strip()

    async def stream(self, system, user):
        # Retry only before the first token arrives; once streaming starts we can't safely replay.
        for attempt in range(3):
            started = False
            try:
                async with self._gate:
                    async for chunk in self._chat.astream([("system", system), ("human", user)]):
                        if chunk.content:
                            started = True
                            yield str(chunk.content)
                return
            except Exception as e:
                wait = _rate_wait(e)
                if started or wait is None or attempt == 2:
                    raise
                await asyncio.sleep(wait)


_llm: LLM | None = None


def get_llm() -> LLM:
    global _llm
    if _llm is None:
        _llm = GroqLLM() if get_settings().groq_api_key else NullLLM()
    return _llm


def set_llm(llm: LLM | None) -> None:
    global _llm
    _llm = llm
