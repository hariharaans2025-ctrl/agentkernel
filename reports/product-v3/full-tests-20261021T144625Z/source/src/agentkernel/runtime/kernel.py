import math
import os
from decimal import Decimal
from time import perf_counter
from uuid import uuid4

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import AttemptRecord, ExecutionResult, InferenceResult, TaskRequest, VerificationResult
from agentkernel.observability import span
from agentkernel.providers.base import InferenceProvider
from agentkernel.router.base import Router
from agentkernel.telemetry.events import ExecutionTelemetryEvent, TelemetryEvent
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.verification.base import Verifier
from agentkernel.verification.mock_verifier import MockVerifier
from .evidence import build_escalation_task

ESCALATION_LADDER = (InferenceTier.LOCAL, InferenceTier.NANO, InferenceTier.SUPER, InferenceTier.ULTRA)


class AgentKernel:
    def __init__(self, router: Router, local_provider: InferenceProvider,
                 nebius_provider: InferenceProvider, telemetry: TelemetryRecorder,
                 verifier: Verifier | None = None, *, max_attempts: int | None = None,
                 tier_schedule: tuple[InferenceTier, ...] | None = None, allow_contract_retry: bool = True) -> None:
        self.router = router
        self.providers = {ProviderType.LOCAL_RTX: local_provider, ProviderType.NEBIUS: nebius_provider}
        self.telemetry = telemetry
        self.verifier = verifier if verifier is not None else MockVerifier()
        if max_attempts is None:
            try:
                max_attempts = int(os.getenv("AGENTKERNEL_MAX_ATTEMPTS", "4"))
            except ValueError as exc:
                raise ValueError("AGENTKERNEL_MAX_ATTEMPTS must be a positive integer.") from exc
        if type(max_attempts) is not int or max_attempts < 1:
            raise ValueError("AGENTKERNEL_MAX_ATTEMPTS must be a positive integer.")
        self.max_attempts = max_attempts
        if tier_schedule is not None and (not tier_schedule or any(
            ESCALATION_LADDER.index(a) > ESCALATION_LADDER.index(b) for a, b in zip(tier_schedule, tier_schedule[1:])
        )):
            raise ValueError("Tier schedule must be nonempty and never downgrade")
        self.tier_schedule = tier_schedule
        self.allow_contract_retry = allow_contract_retry

    async def execute(self, task: TaskRequest) -> ExecutionResult:
        started = perf_counter()
        original = task.model_copy(deep=True)
        routing = await self.router.route(original.model_copy(deep=True))
        attempts: list[AttemptRecord] = []
        inference: InferenceResult | None = None
        execution_id = str(uuid4())
        total_cost: Decimal | None = Decimal("0")
        total_latency = 0.0
        pending_event: TelemetryEvent | None = None
        stopped_reason = "ultra_failed"
        success = False
        initial_index = ESCALATION_LADDER.index(routing.selected_tier)

        schedule = list(self.tier_schedule or ESCALATION_LADDER[initial_index:])
        if schedule[0] != routing.selected_tier:
            raise ValueError("Tier schedule must start at the router's selected tier")
        if schedule[-1] != InferenceTier.ULTRA:
            stopped_reason = "attempts_exhausted"
        for schedule_index, tier in enumerate(schedule):
            if len(attempts) >= self.max_attempts:
                stopped_reason = "max_attempts_reached"
                break
            provider_type = ProviderType.LOCAL_RTX if tier == InferenceTier.LOCAL else ProviderType.NEBIUS
            provider = self.providers[provider_type]
            if original.max_cost_usd is not None:
                estimate = provider.estimate_cost_usd(tier)
                if total_cost is None or estimate is None or not math.isfinite(estimate) or estimate < 0:
                    stopped_reason = "cost_estimate_unavailable"
                    break
                if total_cost + Decimal(str(estimate)) > Decimal(str(original.max_cost_usd)):
                    stopped_reason = "budget_exceeded"
                    break
            enriched = build_escalation_task(original, attempts) if attempts else original.model_copy(deep=True)
            if original.max_latency_ms is not None and (perf_counter() - started) * 1000 >= original.max_latency_ms:
                stopped_reason = "latency_limit_exceeded"
                break
            # Commit the escalation flag only when the next call will actually start.
            if pending_event is not None:
                pending_event.escalated_after_attempt = pending_event.tier != tier
                self.telemetry.record(pending_event)
                pending_event = None
            route = routing.model_copy(deep=True)
            route.selected_tier = tier
            route.selected_provider = provider_type
            if attempts:
                action = "Retrying" if attempts[-1].tier == tier else "Escalated from"
                route.reason = f"{action} {attempts[-1].tier.value} after verification failure: {attempts[-1].verification_reason[:300]}"
            inference, verification = await self._perform_attempt(original, enriched, route, provider, attempts)
            attempt = AttemptRecord(
                attempt_number=len(attempts) + 1, tier=tier, provider=provider_type,
                model=inference.metadata.get("model"), input_prompt=enriched.prompt,
                output_text=inference.output_text, status=inference.status, latency_ms=inference.latency_ms,
                input_tokens=inference.input_tokens, output_tokens=inference.output_tokens,
                estimated_cost_usd=inference.estimated_cost_usd,
                verification_status="PASSED" if verification.passed else "FAILED",
                verification_reason=verification.reason, verification_evidence=verification.evidence,
                verifier_name=verification.verifier_name, metadata=inference.metadata,
            )
            attempts.append(attempt)
            total_cost = (total_cost + Decimal(str(inference.estimated_cost_usd))
                          if total_cost is not None and inference.estimated_cost_usd is not None else None)
            total_latency = math.fsum(item.latency_ms for item in attempts)
            pending_event = TelemetryEvent(
                execution_id=execution_id, task_id=original.task_id, route=route, provider=provider_type, tier=tier,
                difficulty=route.difficulty, confidence=route.confidence, latency_ms=inference.latency_ms,
                input_tokens=inference.input_tokens, output_tokens=inference.output_tokens,
                estimated_cost_usd=inference.estimated_cost_usd, status=inference.status, metadata=inference.metadata,
                attempt_number=attempt.attempt_number, model=attempt.model,
                verification_passed=verification.passed, verification_reason=verification.reason,
                cumulative_cost=float(total_cost) if total_cost is not None else None, cumulative_latency=total_latency,
            )
            if verification.passed:
                success, stopped_reason = True, "verification_passed"
                break
            if self.allow_contract_retry and verification.evidence.get("error_code") == "invalid_model_output" and verification.retryable:
                if schedule_index + 1 == len(schedule) or schedule[schedule_index + 1] != tier:
                    schedule.insert(schedule_index + 1, tier)
            if not verification.retryable:
                stopped_reason = "invalid_model_output" if verification.evidence.get("error_code") == "invalid_model_output" else "verification_not_retryable"
                break

        if pending_event is not None:
            self.telemetry.record(pending_event)
        metadata = {"execution_id": execution_id, "wall_elapsed_ms": (perf_counter() - started) * 1000,
                    "latency_basis": "sum_of_inference_attempts",
                    "verifiers": sorted({attempt.verifier_name for attempt in attempts}),
                    "contains_mock_inference": any(attempt.status == ExecutionStatus.MOCK for attempt in attempts)}
        result = ExecutionResult(
            task_id=original.task_id, success=success, final_output=inference.output_text if inference else "",
            final_tier=attempts[-1].tier if attempts else None, attempts=attempts,
            total_latency_ms=total_latency, total_cost_usd=float(total_cost) if total_cost is not None else None, stopped_reason=stopped_reason,
            metadata=metadata, routing=routing, inference=inference,
        )
        self.telemetry.record(ExecutionTelemetryEvent(
            execution_id=execution_id, task_id=original.task_id, success=success, number_of_attempts=len(attempts),
            starting_tier=routing.selected_tier, final_tier=result.final_tier,
            total_cost=result.total_cost_usd, total_latency=total_latency, stopped_reason=stopped_reason, metadata=metadata,
        ))
        return result

    async def _perform_attempt(self, original, enriched, route, provider, attempts):
        if original.metadata.get('bounded_concurrency') and original.metadata.get('phase') == 'repair':
            async with span('repair_' + str(len(attempts) + 1), current_tier=route.selected_tier.value):
                if route.selected_tier == InferenceTier.ULTRA:
                    async with span('ultra_escalation', current_tier='ULTRA'):
                        return await self._call_and_verify(original, enriched, route, provider, attempts)
                return await self._call_and_verify(original, enriched, route, provider, attempts)
        if original.metadata.get("trace_escalation_tier") == route.selected_tier.value:
            async with span("ultra_escalation", current_tier=route.selected_tier.value, attempt_number=len(attempts) + 1):
                return await self._call_and_verify(original, enriched, route, provider, attempts)
        return await self._call_and_verify(original, enriched, route, provider, attempts)

    async def _call_and_verify(self, original, enriched, route, provider, attempts):
        attempt_started = perf_counter()
        try:
            name = original.metadata.get("inference_span_names", {}).get(route.selected_tier.value, route.selected_tier.value.lower() + "_inference")
            async with span(name, run_type="llm", task_id=original.task_id,
                            current_tier=route.selected_tier.value, attempt_number=len(attempts) + 1,
                            route_reason=route.reason) as observed:
                inference = await provider.generate(enriched.model_copy(deep=True), route.model_copy(deep=True))
                observed.update(model_id=inference.metadata.get("model"),
                    input_tokens=inference.metadata.get("actual_input_tokens", inference.input_tokens),
                    output_tokens=inference.metadata.get("actual_output_tokens", inference.output_tokens),
                    model_latency_ms=inference.latency_ms, retry_count=inference.metadata.get("retry_count", 0),
                    request_id=inference.metadata.get("request_id"), finish_reason=inference.metadata.get("finish_reason"),
                    error_code=inference.metadata.get("error_code"), status=inference.status.value,
                    execution_mode=inference.metadata.get("execution_mode"))
            if (inference.task_id != original.task_id or inference.provider != route.selected_provider or inference.tier != route.selected_tier):
                raise ValueError("Provider result does not match the requested route")
        except Exception as exc:
            inference = InferenceResult(
                task_id=original.task_id, provider=route.selected_provider, tier=route.selected_tier,
                output_text="Provider execution failed.", status=ExecutionStatus.FAILED,
                latency_ms=(perf_counter() - attempt_started) * 1000, input_tokens=0, output_tokens=0,
                estimated_cost_usd=0, metadata={"error_type": type(exc).__name__, "usage_unknown": True},
            )
        try:
            verification = await self.verifier.verify(
                original.model_copy(deep=True), inference.model_copy(deep=True),
                [attempt.model_copy(deep=True) for attempt in attempts],
            )
            if inference.status == ExecutionStatus.FAILED:
                verification = VerificationResult(
                    passed=False, reason="Inference failed. " + verification.reason,
                    retryable=verification.retryable and inference.metadata.get("retryable", True),
                    evidence={**verification.evidence, "inference_error": inference.output_text,
                              "error_type": inference.metadata.get("error_type")},
                    verifier_name=verification.verifier_name,
                )
        except Exception as exc:
            verification = VerificationResult(
                passed=False, reason="Verifier raised an error; output was not verified.",
                retryable=not original.metadata.get('bounded_concurrency', False),
                evidence={"error_type": type(exc).__name__, 'infrastructure_failure': True}, verifier_name=type(self.verifier).__name__,
            )
        return inference, verification
