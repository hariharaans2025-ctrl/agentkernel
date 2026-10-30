import os
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest
from agentkernel.observability import configured_observer, trace, span
from agentkernel.observability.base import ObservabilityBackend
from agentkernel.providers.base import InferenceProvider
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder

from .analyzer.fingerprints import fingerprints
from .analyzer.routing import ConcurrencyRouter
from .campaign.manager import StressCampaignManager
from .campaign.models import CampaignResult
from .compile.compiler import CCompiler
from .instrumentation.sanitizer import SanitizerConfig, parse_sanitizer
from .instrumentation.sanitizer import instrumented_task, runtime_unavailable
from .mock_inference import mock_concurrency_response
from .models import ConcurrencyTask
from .repair.prompts import SYSTEM_PROMPT, repair_prompt, triage_prompt
from .sandbox.local import safe_path
from .sandbox.nebius import NebiusSandboxBackend
from .verification.repair_verifier import RepairVerifier, TriageVerifier
from agentkernel.knowledge import ConditionalGrounding


class ConcurrencyPolicy(BaseModel):
    max_super_repairs: int = Field(default=1, ge=1, le=4)
    max_ultra_repairs: int = Field(default=1, ge=1, le=4)
    max_total_attempts: int = Field(default=3, ge=1, le=20)
    max_nano_triage: int = Field(default=1, ge=1, le=2)
    max_fixed_attempts: int = Field(default=1, ge=1, le=4)
    repair_output_tokens: int = Field(default=2048, ge=128, le=8192)
    triage_output_tokens: int = Field(default=768, ge=128, le=2048)
    max_input_bytes: int = Field(default=48000, ge=1000, le=120000)
    allow_contract_retry: bool = False
    max_cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_latency_ms: int | None = Field(default=None, ge=0)
    mode: Literal["adaptive", "nano-only", "super-only", "ultra-only"] = "adaptive"


class ConcurrencyJobResult(BaseModel):
    task: str
    status: str = "unresolved"
    route: list[str] = Field(default_factory=list)
    ultra_avoided: bool = True
    baseline: dict[str, Any] = Field(default_factory=dict)
    verification: dict[str, Any] | None = None
    repairs: list[dict[str, Any]] = Field(default_factory=list)
    triage: dict[str, Any] | None = None
    stopped_reason: str = ""
    total_time_ms: float = 0
    inference_latency_ms: float = 0
    execution_latency_ms: float = 0
    inference_tokens: int = 0
    cost_usd: float | None = 0
    inference_mode: str = "mock"
    model_calls: dict[str, int] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConcurrencyJobEvent(BaseModel):
    event_type: str = "concurrency_job"
    task_id: str
    summary: dict[str, Any]


class ConcurrencyBugHunter:
    def __init__(self, provider: InferenceProvider | None = None, telemetry: TelemetryRecorder | None = None,
                 policy: ConcurrencyPolicy | None = None, temporary_parent: Path | None = None, observer: ObservabilityBackend | None = None) -> None:
        if provider is None:
            mode = os.getenv("AGENTKERNEL_NEBIUS_MODE", "mock").lower()
            if mode == "real":
                from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider
                provider = NebiusTokenFactoryProvider(max_retries=0)
            elif mode == "mock":
                provider = MockNebiusProvider(mock_concurrency_response)
            else:
                raise ValueError("AGENTKERNEL_NEBIUS_MODE must be mock or real")
        self.provider = provider
        self.telemetry = telemetry or TelemetryRecorder()
        self.policy = policy or ConcurrencyPolicy(max_total_attempts=int(os.getenv("AGENTKERNEL_MAX_ATTEMPTS", "4")))
        self.temporary_parent = temporary_parent
        self.observer = observer

    async def run(self, task: ConcurrencyTask) -> ConcurrencyJobResult:
        observer = self.observer or configured_observer()
        try:
            async with trace("concurrency_job", observer, task_id=task.task_id, bug_type=task.expected_bug_category) as root:
                result = await self._run(task)
                root.update(status=result.status, starting_tier=result.route[0] if result.route else None,
                            ultra_used=not result.ultra_avoided, ultra_avoided=result.ultra_avoided,
                            verification_passed=result.status == "verified")
                await root.feedback(ultra_used=not result.ultra_avoided, verification_passed=result.status == "verified", final_tier=result.route[-1] if result.route else 'NONE')
        finally:
            try:
                observability = await observer.flush()
            except Exception as exc:
                observability = {'status': 'unavailable', 'error_code': type(exc).__name__}
        result.metadata["observability"] = observability
        self._record_result(result)
        return result

    async def _run(self, task: ConcurrencyTask) -> ConcurrencyJobResult:
        started = perf_counter()
        event_offset = len(self.telemetry.events)
        result = ConcurrencyJobResult(task=task.task_id)
        grounding = ConditionalGrounding()
        result.metadata['grounding'] = await grounding.lookup(task.metadata.get('grounding_reason'))
        result.metadata["execution_backend"] = "nebius"
        def finish(reason: str) -> ConcurrencyJobResult:
            result.stopped_reason = reason
            events = self.telemetry.events[event_offset:]
            result.route = [event.tier.value for event in events]
            result.ultra_avoided = "ULTRA" not in result.route
            result.model_calls = {tier.value: sum(event.tier == tier for event in events) for tier in InferenceTier}
            result.inference_tokens = sum(event.input_tokens + event.output_tokens for event in events)
            result.inference_latency_ms = sum(event.latency_ms for event in events)
            result.cost_usd = sum(event.estimated_cost_usd for event in events) if all(event.estimated_cost_usd is not None for event in events) else None
            result.inference_mode = ("mock" if isinstance(self.provider, MockNebiusProvider) else "real")
            result.total_time_ms = (perf_counter() - started) * 1000
            result.metadata["models"] = sorted({event.model for event in events if event.model})
            result.metadata["starting_tier"] = result.route[0] if result.route else None
            result.metadata["final_tier"] = result.route[-1] if result.route else None
            result.metadata["escalations"] = sum(a != b for a, b in zip(result.route, result.route[1:]))
            result.metadata["routing_reasons"] = [event.route.reason for event in events]
            result.metadata["usage_available"] = all(not event.metadata.get("usage_unknown", False)
                and event.metadata.get("usage_available", True) for event in events)
            result.metadata["inference_measurement"] = "simulated" if result.inference_mode == "mock" else "measured"
            result.metadata["patch_attempts"] = len(result.repairs)
            result.metadata["model_attempts"] = [{"tier": event.tier.value, "model_id": event.model,
                "input_tokens": event.metadata.get("actual_input_tokens"), "output_tokens": event.metadata.get("actual_output_tokens"),
                "latency_ms": event.latency_ms, "retry_count": event.metadata.get("retry_count", 0),
                "reasoning_tokens": event.metadata.get("actual_reasoning_tokens"),
                "requested_max_output_tokens": event.metadata.get("requested_max_output_tokens"),
                "requested_enable_thinking": event.metadata.get("requested_enable_thinking"),
                "error_hint": event.metadata.get("error_hint"),
                "finish_reason": event.metadata.get("finish_reason"), "request_id": event.metadata.get("request_id"),
                "error_code": event.metadata.get("error_code"), "verification_reason": event.verification_reason}
                for event in events]
            return result
        import hashlib
        result.metadata['source_sha256'] = {n: hashlib.sha256(safe_path(task.workspace, n).read_bytes()).hexdigest() for n in task.source_files + task.support_files}
        result.metadata['verification_configuration'] = task.verification_config.model_dump(mode='json')
        async with span('baseline'), NebiusSandboxBackend(temporary_parent=self.temporary_parent) as sandbox:
            await sandbox.upload_project(task.workspace, task.source_files + task.support_files)
            async with span('compile'), span("baseline_compile", task_id=task.task_id) as observed:
                build = await CCompiler().compile(task, sandbox)
                observed.update(build_success=build.success, duration_ms=build.duration_ms)
                await observed.feedback(build_success=build.success)
            result.execution_latency_ms += build.duration_ms
            if not build.success:
                result.status = "execution_blocked" if build.metadata.get("execution_policy_blocked") else "build_failed"
                result.baseline = {"build": build.model_dump()}
                return finish("baseline_build_failed")
            async with span('campaign'), span("baseline_stress_campaign", task_id=task.task_id) as observed:
                baseline = await StressCampaignManager().run(task, sandbox)
                observed.update(baseline_runs=len(baseline.runs), baseline_passes=baseline.counts.get("PASS", 0),
                    baseline_deadlocks=baseline.counts.get("TIMEOUT", 0) + baseline.counts.get("POSSIBLE_DEADLOCK", 0),
                    baseline_races=baseline.counts.get("RACE_DETECTED", 0), baseline_crashes=baseline.counts.get("CRASH", 0),
                    infrastructure_failures=baseline.infrastructure_failures, duration_ms=baseline.duration_ms)
                await observed.feedback(deadlock_detected=bool(baseline.counts.get("TIMEOUT", 0) + baseline.counts.get("POSSIBLE_DEADLOCK", 0)),
                                        race_detected=bool(baseline.counts.get("RACE_DETECTED", 0)))
            result.execution_latency_ms += baseline.duration_ms
            ordinary_baseline = baseline
            result.baseline = {"build_passed": True, **baseline.compact(), "sanitizer": {"status": "not_configured"}}
            if baseline.execution_blocked:
                result.status = "execution_blocked"
                return finish("host_execution_policy_blocked")
            if baseline.infrastructure_failures == len(baseline.runs):
                result.status = "execution_unavailable"
                return finish("no_executable_baseline_runs")
            config = task.verification_config
            if config.sanitizer_enabled or config.sanitizer_required:
                sanitizer = SanitizerConfig(enabled=True, required=config.sanitizer_required)
                tsan_task = instrumented_task(task)
                instrumented = await CCompiler().compile(tsan_task, sandbox, sanitizer.flags)
                result.execution_latency_ms += instrumented.duration_ms
                if not instrumented.success:
                    result.baseline["sanitizer"] = {"status": "unavailable", "build": instrumented.model_dump()}
                    if instrumented.metadata.get("execution_policy_blocked"):
                        result.status = "execution_blocked"
                        return finish("host_execution_policy_blocked")
                    if config.sanitizer_required:
                        result.status = "tooling_unavailable"
                        return finish("required_thread_sanitizer_unavailable")
                else:
                    observed = await StressCampaignManager().run(tsan_task, sandbox, runs=config.sanitizer_runs)
                    result.execution_latency_ms += observed.duration_ms
                    if observed.execution_blocked:
                        result.baseline["sanitizer"] = {"status": "execution_blocked", "campaign": observed.compact()}
                        result.status = "execution_blocked"
                        return finish("host_execution_policy_blocked")
                    for run in observed.runs:
                        run.run_id = "tsan-" + run.run_id
                    result.baseline["sanitizer"] = {"status": "passed" if not observed.failed_runs else "failed",
                                                    "campaign": observed.compact(),
                                                    "findings": [f.model_dump() for r in observed.runs for f in parse_sanitizer(r.stderr)]}
                    if any(runtime_unavailable(r.stderr) for r in observed.runs) or observed.infrastructure_failures:
                        result.baseline['sanitizer']['status'] = 'unavailable'
                        result.status = 'tooling_unavailable'
                        return finish('required_thread_sanitizer_runtime_unavailable')
                    combined_counts = dict(baseline.counts)
                    for key, count in observed.counts.items():
                        combined_counts[key] = combined_counts.get(key, 0) + count
                    baseline = CampaignResult(task_id=task.task_id, runs=baseline.runs + observed.runs,
                                              counts=combined_counts, duration_ms=baseline.duration_ms + observed.duration_ms)
        if baseline.failed_runs == 0:
            result.status = "baseline_clean"
            return finish("no_failure_observed")
        async with span('analysis'), span('fingerprint'), span("fingerprint_analysis") as observed:
            normalized = [item.model_dump(mode="json") for item in fingerprints(baseline)]
            observed.update(fingerprint_count=len(normalized))
        result.baseline["fingerprints"] = normalized
        context: dict[str, Any] = {"baseline": baseline.compact(), "fingerprints": normalized,
                                   "sanitizer": result.baseline["sanitizer"],
                                   "high_risk": task.metadata.get("high_risk", False)}
        context['original_task'] = {'task_id': task.task_id, 'expected_behavior': task.expected_behavior,
            'description': task.metadata.get('fixture_description'), 'verification': task.verification_config.model_dump(mode='json')}
        remaining = self.policy.max_total_attempts
        spent = 0.0
        def model_task(phase: str, prompt: str) -> TaskRequest:
            elapsed = (perf_counter() - started) * 1000
            return TaskRequest(task_id=task.task_id, task_type="concurrency_" + phase, prompt=prompt,
                               metadata={"phase": phase, "system_prompt": SYSTEM_PROMPT, "concurrency_context": context,
                                         'bounded_concurrency': True, 'allow_contract_retry': self.policy.allow_contract_retry, 'max_input_bytes': self.policy.max_input_bytes,
                                         "structured_output": True, "max_output_tokens": self.policy.triage_output_tokens if phase == "triage" else self.policy.repair_output_tokens,
                                         "trace_escalation_tier": "ULTRA",
                                         "inference_span_names": {"NANO": "nano_triage" if phase == "triage" else "nano_diagnosis",
                                                                  "SUPER": "super_diagnosis", "ULTRA": "ultra_diagnosis"}},
                               max_cost_usd=None if self.policy.max_cost_usd is None else max(0, self.policy.max_cost_usd - spent),
                               max_latency_ms=None if self.policy.max_latency_ms is None else max(0, int(self.policy.max_latency_ms - elapsed)))
        if self.policy.mode == "adaptive":
            async with span('analysis'), span('nano'):
                triage = await AgentKernel(ConcurrencyRouter(), LocalRTXProvider(), self.provider, self.telemetry,
                                           TriageVerifier(), max_attempts=min(self.policy.max_nano_triage, remaining), allow_contract_retry=False,
                                           tier_schedule=(InferenceTier.NANO,) * self.policy.max_nano_triage).execute(model_task("triage", triage_prompt(context)))
            remaining -= len(triage.attempts)
            spent += triage.total_cost_usd or 0
            if not triage.success:
                return finish("triage_" + triage.stopped_reason)
            result.triage = triage.attempts[-1].verification_evidence
            context["nano_summary"] = result.triage
            if result.triage.get('grounding_reason'):
                result.metadata['grounding'] = await grounding.lookup(result.triage['grounding_reason'])
        if remaining <= 0:
            return finish("max_attempts_reached")
        sources = {name: safe_path(task.workspace, name).read_text(encoding="utf-8") for name in task.source_files}
        if sum(len(source) for source in sources.values()) > 120000:
            return finish("source_context_limit_exceeded")
        context.update({"sources": sources, "build_command": task.build_command})
        context['external_grounding'] = result.metadata['grounding']
        fixed = {"nano-only": InferenceTier.NANO, "super-only": InferenceTier.SUPER, "ultra-only": InferenceTier.ULTRA}.get(self.policy.mode)
        router = ConcurrencyRouter(fixed or (InferenceTier.ULTRA if task.metadata.get('explicit_ultra_escalation') else InferenceTier.SUPER))
        repair_task = model_task("repair", repair_prompt(context))
        initial = await router.route(repair_task)
        if fixed:
            schedule = (fixed,) * self.policy.max_fixed_attempts
        elif initial.selected_tier == InferenceTier.ULTRA:
            schedule = (InferenceTier.ULTRA,) * self.policy.max_ultra_repairs
        else:
            schedule = (InferenceTier.SUPER,) * self.policy.max_super_repairs + (InferenceTier.ULTRA,) * self.policy.max_ultra_repairs
        verifier = RepairVerifier(task, ordinary_baseline, self.temporary_parent)
        execution = await AgentKernel(router, LocalRTXProvider(), self.provider, self.telemetry, verifier,
                                      max_attempts=remaining, tier_schedule=schedule, allow_contract_retry=self.policy.allow_contract_retry).execute(repair_task)
        result.metadata['attempt_details'] = [a.model_dump(mode='json', exclude={'input_prompt'}) for a in execution.attempts]
        result.metadata['format_rejections'] = sum(a.verification_evidence.get('error_code') == 'invalid_model_output' for a in execution.attempts)
        result.metadata['infrastructure_failures'] = sum(bool(a.verification_evidence.get('infrastructure_failure')) for a in execution.attempts)
        result.repairs = verifier.results
        result.status = "verified" if execution.success else "unresolved"
        if any(entry.get("verification", {}).get("evidence", {}).get("execution_blocked") for entry in verifier.results):
            result.status = "execution_blocked"
        for entry in verifier.results:
            if "verification" in entry:
                result.verification = entry["verification"]
                result.execution_latency_ms += entry["verification"]["duration_ms"]
        return finish(execution.stopped_reason)

    def _record_result(self, result: ConcurrencyJobResult) -> None:
        summary = result.model_dump(mode="json", exclude={"repairs"})
        if result.verification:
            summary["verification"] = {key: result.verification[key] for key in (
                "passed", "build_passed", "total_runs", "passed_runs", "failed_runs", "race_count", "deadlock_count",
                "crash_count", "infrastructure_failures", "observed_program_failures", "regressions", "duration_ms", "reason")}
            summary["verification"]["sanitizer_status"] = result.verification["evidence"].get("sanitizer", {}).get("status")
            summary["verification"]["sanitizer_findings"] = [
                {key: value for key, value in finding.items() if key != "raw_summary"}
                for finding in result.verification["sanitizer_findings"][:5]]
        summary["patch_hashes"] = [entry["patch"]["patch_hash"] for entry in result.repairs if "patch" in entry]
        self.telemetry.record(ConcurrencyJobEvent(task_id=result.task, summary=summary))
