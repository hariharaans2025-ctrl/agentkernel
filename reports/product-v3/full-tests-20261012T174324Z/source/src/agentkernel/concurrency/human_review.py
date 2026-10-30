"""Optional human review export. Live Toloka transport is deliberately pending."""
from typing import Protocol
from pydantic import BaseModel, Field
from agentkernel.telemetry.redaction import redact


class ReviewScores(BaseModel):
    readability: int = Field(ge=1, le=5)
    unnecessary_serialization: int = Field(ge=1, le=5)
    concurrency_preservation: int = Field(ge=1, le=5)
    maintainability: int = Field(ge=1, le=5)
    diagnosis_clarity: int = Field(ge=1, le=5)
    notes: str = Field(default='', max_length=2000)


class HumanReviewAdapter(Protocol):
    async def submit(self, package: dict) -> dict: ...


def review_package(job):
    if job.status != 'verified' or not job.verification or not job.verification.get('passed'):
        raise ValueError('Only executably verified repairs are eligible for human review')
    return redact({'task': job.task, 'source_sha256': job.metadata.get('source_sha256'),
        'repairs': [{'patch': r.get('proposal', {}).get('patch'), 'diagnosis': r.get('proposal', {}).get('diagnosis'),
                    'patch_hash': r.get('patch', {}).get('patch_hash')} for r in job.repairs if r.get('verification', {}).get('passed')],
        'rubric': ReviewScores.model_json_schema(), 'verification': job.verification,
        'notice': 'Human scores supplement executable verification; they cannot change its outcome.'})


class PendingTolokaAdapter:
    async def submit(self, package):
        return {'status': 'live_integration_pending', 'submitted': False, 'task': package['task']}
