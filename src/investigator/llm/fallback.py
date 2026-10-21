"""Sending a request to a backup model when the main one still fails after its retries."""

from investigator.llm.gateway import ModelError, ModelGateway
from investigator.llm.messages import ChatRequest, ChatResponse
from investigator.tracing import ModelFellBack, Tracer


class FallbackGateway:
    """Tries the main model, and if it still fails, sends the same request to the backup.

    Each gateway does its own retrying. Every model call is already traced with the model
    that answered it; this also traces each switch to the backup, and why.
    """

    def __init__(
        self,
        main: ModelGateway,
        backup: ModelGateway,
        *,
        main_model: str,
        backup_model: str,
        tracer: Tracer,
    ) -> None:
        self._main = main
        self._backup = backup
        self._main_model = main_model
        self._backup_model = backup_model
        self._tracer = tracer

    async def complete(self, request: ChatRequest) -> ChatResponse:
        try:
            return await self._main.complete(request)
        except ModelError as error:
            self._tracer.record(
                ModelFellBack(
                    purpose=request.purpose,
                    failed_model=self._main_model,
                    backup_model=self._backup_model,
                    error=f"{type(error).__name__}: {error}",
                )
            )
        return await self._backup.complete(request)
