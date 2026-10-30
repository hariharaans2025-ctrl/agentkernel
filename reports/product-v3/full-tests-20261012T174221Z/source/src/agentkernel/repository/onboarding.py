import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig, SemanticCheck
from agentkernel.concurrency.sandbox.local import safe_path


class Budgets(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    max_model_calls: int = Field(default=3, ge=1, le=10)
    max_total_tokens: int = Field(default=24000, ge=1)
    max_input_tokens_per_call: int = Field(default=6000, ge=1)
    max_output_tokens_per_call: int = Field(default=2048, ge=1)
    max_wall_seconds: int = Field(default=1800, ge=1)

    @model_validator(mode='after')
    def feasible(self):
        if self.max_input_tokens_per_call + self.max_output_tokens_per_call > self.max_total_tokens:
            raise ValueError('Budget must accommodate one maximum-sized call')
        return self


class RepositorySemantic(SemanticCheck):
    model_config = ConfigDict(extra='forbid', strict=True)


class RepositoryVerification(VerificationConfig):
    model_config = ConfigDict(extra='forbid', strict=True)
    semantic_checks: list[RepositorySemantic] = Field(default_factory=list)


class RepositoryContract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    schema_version: Literal[1] = 1
    project: str = Field(pattern=r'^[a-z][a-z0-9_-]{0,63}$')
    description: str = Field(min_length=1, max_length=2000)
    origin: Literal['user_repository', 'synthetic_example']
    source_files: list[str] = Field(min_length=1, max_length=500)
    support_files: list[str] = Field(default_factory=list, max_length=500)
    build_command: list[str] = Field(min_length=1)
    run_command: list[str] = Field(min_length=1)
    binary_path: str
    expected_behavior: str = 'PASS'
    compile_timeout_seconds: int = Field(default=30, ge=1, le=120)
    max_runtime_seconds: int = Field(default=2, ge=1, le=120)
    baseline_runs: int = Field(default=3, ge=1, le=100)
    verification: RepositoryVerification
    budgets: Budgets = Field(default_factory=Budgets)
    execution_backend: Literal['nebius'] = 'nebius'
    max_upload_bytes: int = Field(default=2000000, ge=1, le=20000000)

    @field_validator('source_files', 'support_files')
    @classmethod
    def valid_files(cls, values):
        for value in values:
            parts = value.split('/')
            if (not value or '\\' in value or ':' in value or '\x00' in value
                    or any(p in {'', '.', '..'} or p.startswith('.') for p in parts)
                    or PurePosixPath(value).suffix.lower() in {'.pem', '.key', '.p12', '.pfx'}
                    or PurePosixPath(value).name.lower() in {'credentials', 'credentials.json', 'secrets.json'}):
                raise ValueError('Only explicit nonsecret relative project files are allowed')
        return values

    @model_validator(mode='after')
    def complete(self):
        all_files = self.source_files + self.support_files
        if len({s.casefold() for s in all_files}) != len(all_files):
            raise ValueError('Editable and protected files must be distinct, including case aliases')
        if any(PurePosixPath(s).suffix.lower() not in {'.c', '.h', '.cc', '.cpp', '.hpp'} for s in self.source_files):
            raise ValueError('Initial editable scope supports C/C++ source only')
        v = self.verification
        if not v.required_original_tests or not v.original_test_commands:
            raise ValueError('Repository onboarding requires original tests')
        if not v.semantic_checks or not all(c.required for c in v.semantic_checks):
            raise ValueError('Repository onboarding requires protected semantic checks')
        if not v.sanitizer_required or not v.sanitizer_enabled:
            raise ValueError('Initial repository workflow requires TSan')
        if not v.required_build_success or v.allowed_deadlocks or v.allowed_races or v.allowed_crashes:
            raise ValueError('Repository verification cannot accept observed concurrency failures')
        if v.stress_runs < 100 or v.sanitizer_runs < 3:
            raise ValueError('Repository verification requires at least 100 stress and 3 TSan runs')
        for command in [self.build_command, self.run_command, *v.original_test_commands,
                        *(c.build_command for c in v.semantic_checks), *(c.run_command for c in v.semantic_checks)]:
            if any(not isinstance(s, str) or not s or '\x00' in s for s in command):
                raise ValueError('Commands must contain nonempty argv strings')
        return self


def create_plan(root: Path, config: Path, output: Path):
    root = root.resolve(strict=True)
    if config.stat().st_size > 65536:
        raise ValueError('Contract exceeds 64 KiB')
    contract = RepositoryContract.model_validate_json(config.read_text(encoding='utf-8'))
    entries, total = {}, 0
    for name in contract.source_files + contract.support_files:
        path = safe_path(root, name)
        if not path.is_file() or path.stat().st_size > 2000000:
            raise ValueError('Configured file missing or larger than sandbox upload limit')
        data = path.read_bytes()
        total += len(data)
        entries[name] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
                         'editable': name in contract.source_files}
    if total > contract.max_upload_bytes:
        raise ValueError('Upload budget exceeded')
    binary = safe_path(root, contract.binary_path)
    if binary.exists() or contract.binary_path.casefold() in {s.casefold() for s in entries}:
        raise ValueError('Binary path must not overwrite an existing repository file')
    task = ConcurrencyTask(task_id=contract.project, workspace=root,
        source_files=contract.source_files, support_files=contract.support_files,
        build_command=contract.build_command, run_command=contract.run_command,
        binary_path=contract.binary_path, expected_behavior=contract.expected_behavior,
        compile_timeout_seconds=contract.compile_timeout_seconds,
        max_runtime_seconds=contract.max_runtime_seconds, stress_runs=contract.baseline_runs,
        verification_config=contract.verification,
        metadata={'origin': contract.origin, 'repository_workflow_version': 1})
    normalized = contract.model_dump(mode='json')
    identity = {'contract': normalized, 'files': entries}
    plan = {'schema_version': 1, 'state': 'PLANNED_NOT_EXECUTED', 'contract': normalized,
            'plan_sha256': hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            'files': entries, 'upload_bytes': total, 'task': task.model_dump(mode='json'),
            'execution_backend': 'nebius', 'model_calls': 0,
            'metrics': {'input_tokens': None, 'output_tokens': None, 'cost_usd': None,
                        'inference_ms': None, 'verification_ms': None, 'end_to_end_ms': None,
                        'verified': None, 'semantic_passed': None, 'tsan_passed': None},
            'limitations': ['Budgets are a contract; production runtime integration is not enabled.',
                            'Commands require review before execution. A valid plan is not permission to execute.',
                            'File identity is content-based; no Git checkout or commit verification is performed.']}
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'plan.json').open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, indent=2)
    return plan
