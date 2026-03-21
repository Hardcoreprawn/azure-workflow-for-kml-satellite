from collections.abc import Callable, Iterable
from typing import Any

import azure.functions as func

class Blueprint:
    def orchestration_trigger(
        self,
        context_name: str,
        orchestration: str | None = None,
    ) -> Callable[..., Any]: ...
    def activity_trigger(
        self,
        input_name: str,
        activity: str | None = None,
    ) -> Callable[..., Any]: ...
    def event_grid_trigger(
        self,
        arg_name: str,
        data_type: func.DataType | str | None = None,
        **kwargs: Any,
    ) -> Callable[..., Any]: ...
    def route(
        self,
        route: str | None = None,
        trigger_arg_name: str = "req",
        binding_arg_name: str = "$return",
        methods: Iterable[str] | None = None,
        auth_level: func.AuthLevel | str | None = None,
        trigger_extra_fields: dict[str, Any] | None = None,
        binding_extra_fields: dict[str, Any] | None = None,
    ) -> Callable[..., Any]: ...
    def durable_client_input(
        self,
        client_name: str,
        task_hub: str | None = None,
        connection_name: str | None = None,
    ) -> Callable[..., Any]: ...
