import random

from pydantic import BaseModel, Field


class StressSchedule(BaseModel):
    seed: int = 0
    workers: list[int] = Field(default_factory=lambda: [2])
    workloads: list[int] = Field(default_factory=lambda: [1000])
    max_start_delay_us: int = Field(default=100, ge=0, le=1000000)

    def environment_for(self, index: int) -> dict[str, str]:
        rng = random.Random(self.seed + index)
        return {"AK_SEED": str(rng.randrange(2**31)), "AK_WORKERS": str(rng.choice(self.workers)),
                "AK_WORKLOAD": str(rng.choice(self.workloads)),
                "AK_START_DELAY_US": str(rng.randrange(self.max_start_delay_us + 1))}
