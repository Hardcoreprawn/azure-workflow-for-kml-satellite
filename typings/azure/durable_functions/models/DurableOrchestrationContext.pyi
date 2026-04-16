from collections.abc import Callable
from datetime import datetime
from typing import Any

from azure.durable_functions.models.RetryOptions import RetryOptions
from azure.durable_functions.models.Task import TaskBase

class DurableOrchestrationContext:
    @property
    def instance_id(self) -> str: ...
    @property
    def current_utc_datetime(self) -> datetime: ...
    def get_input(self) -> Any | None: ...
    def call_activity(
        self,
        name: str | Callable[..., Any],
        input_: Any | None = None,
    ) -> TaskBase: ...
    def call_activity_with_retry(
        self,
        name: str | Callable[..., Any],
        retry_options: RetryOptions,
        input_: Any | None = None,
    ) -> TaskBase: ...
    def task_all(self, activities: list[TaskBase]) -> TaskBase: ...
    def task_any(self, activities: list[TaskBase]) -> TaskBase: ...
    def set_custom_status(self, status: Any) -> None: ...
    def create_timer(self, fire_at: datetime) -> TaskBase: ...
    def call_sub_orchestrator(
        self,
        name: str,
        input_: Any | None = None,
        instance_id: str | None = None,
    ) -> TaskBase: ...
