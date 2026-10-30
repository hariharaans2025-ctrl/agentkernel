from enum import Enum


class TaskDifficulty(str, Enum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    UNKNOWN = "UNKNOWN"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class InferenceTier(str, Enum):
    LOCAL = "LOCAL"
    NANO = "NANO"
    SUPER = "SUPER"
    ULTRA = "ULTRA"


class ProviderType(str, Enum):
    LOCAL_RTX = "LOCAL_RTX"
    NEBIUS = "NEBIUS"


class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    MOCK = "MOCK"
