from typing import Any

from azure.durable_functions.models.DurableOrchestrationStatus import (
    DurableOrchestrationStatus,
)

class DurableOrchestrationClient:
    async def get_status(
        self,
        instance_id: str,
        show_history: bool = False,
        show_history_output: bool = False,
        show_input: bool = False,
    ) -> DurableOrchestrationStatus: ...
    async def start_new(
        self,
        orchestration_function_name: str,
        instance_id: str | None = None,
        client_input: Any | None = None,
        version: str | None = None,
    ) -> str: ...
    async def terminate(self, instance_id: str, reason: str) -> None: ...
    async def purge_instance_history(self, instance_id: str) -> Any: ...
