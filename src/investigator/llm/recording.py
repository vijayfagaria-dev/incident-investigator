"""Recording model replies during a run, and replaying them without a model.

A cassette maps each request, by a digest of its full content, to the reply it got and
how long that reply took. Replay answers a request with its recorded reply after the
recorded delay, sped up. Keeping the relative timing makes concurrent agents finish in
the recorded order, so the board, and therefore every later request, comes out the same.
"""

import asyncio
import gzip
import hashlib
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Self

from investigator.domain.base import DomainModel
from investigator.llm.gateway import ModelGateway, ModelRejected
from investigator.llm.messages import ChatRequest, ChatResponse


def request_digest(request: ChatRequest) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()


class Recording(DomainModel):
    purpose: str
    digest: str
    elapsed_s: float
    """From the request reaching the gateway to its reply, including retries and waits."""
    response: ChatResponse


class Cassette:
    def __init__(self, recordings: list[Recording] | None = None) -> None:
        self.recordings = recordings or []

    @classmethod
    def load(cls, path: Path) -> Self:
        with gzip.open(path, "rt", encoding="utf-8") as lines:
            return cls([Recording.model_validate_json(line) for line in lines if line.strip()])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as out:
            out.writelines(f"{recording.model_dump_json()}\n" for recording in self.recordings)


class RecordingGateway:
    """Passes requests through and records every reply in a cassette."""

    def __init__(
        self,
        inner: ModelGateway,
        cassette: Cassette,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._cassette = cassette
        self._clock = clock

    async def complete(self, request: ChatRequest) -> ChatResponse:
        started = self._clock()
        response = await self._inner.complete(request)
        self._cassette.recordings.append(
            Recording(
                purpose=request.purpose,
                digest=request_digest(request),
                elapsed_s=self._clock() - started,
                response=response,
            )
        )
        return response


class ReplayGateway:
    """Answers from a cassette, never from a model.

    A request that matches no recording exactly gets the next unused reply recorded for
    the same agent role, and counts as a divergence: the replay is then a close
    reconstruction rather than an exact one.
    """

    def __init__(
        self,
        cassette: Cassette,
        *,
        speedup: float = 50.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._unused = list(cassette.recordings)
        self._speedup = speedup
        self._sleep = sleep
        self.divergences = 0

    @property
    def remaining(self) -> int:
        """Recorded replies not yet used."""
        return len(self._unused)

    async def complete(self, request: ChatRequest) -> ChatResponse:
        recording = self._take(request)
        await self._sleep(recording.elapsed_s / self._speedup)
        return recording.response

    def _take(self, request: ChatRequest) -> Recording:
        digest = request_digest(request)
        match = next((r for r in self._unused if r.digest == digest), None)
        if match is None:
            match = next((r for r in self._unused if r.purpose == request.purpose), None)
            if match is None:
                raise ModelRejected(f"the recording has no reply left for {request.purpose}")
            self.divergences += 1
        self._unused.remove(match)
        return match
