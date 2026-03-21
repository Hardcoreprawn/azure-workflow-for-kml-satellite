from enum import Enum

class OrchestrationRuntimeStatus(Enum):
    Running = "Running"
    Completed = "Completed"
    ContinuedAsNew = "ContinuedAsNew"
    Failed = "Failed"
    Canceled = "Canceled"
    Terminated = "Terminated"
    Pending = "Pending"
    Suspended = "Suspended"
