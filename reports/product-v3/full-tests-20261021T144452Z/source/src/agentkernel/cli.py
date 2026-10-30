import argparse
import asyncio
import json
import sys
from pathlib import Path

from agentkernel.core.enums import ExecutionStatus, InferenceTier, ProviderType
from agentkernel.core.models import TaskRequest
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in {"concurrency", "nebius"}:
        from agentkernel.concurrency.cli import main as concurrency_main
        concurrency_main(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description="AgentKernel local inference and mock tier demo")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--task")
    action.add_argument("--health", action="store_true", help="Check the real local backend and configured model")
    parser.add_argument("--task-id", default="ci_001")
    parser.add_argument("--task-type", default="ci_failure")
    parser.add_argument("--privacy-sensitive", action="store_true")
    parser.add_argument("--telemetry-jsonl", type=Path)
    parser.add_argument("--verification-plan", help='Mock outcomes as JSON, e.g. {"LOCAL": false, "SUPER": true}')
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--max-latency-ms", type=int)
    parser.add_argument("--max-attempts", type=int, help="Override AGENTKERNEL_MAX_ATTEMPTS (default 4)")
    args = parser.parse_args()
    local = LocalRTXProvider()
    if args.health:
        health = asyncio.run(local.health_check())
        print(f"Local backend:\nBackend: {health.backend}\nStatus: {'AVAILABLE' if health.available else 'UNAVAILABLE'}")
        print(f"Model: {health.configured_model or '(not configured)'}")
        if health.error:
            print(f"Reason: {health.error}")
        raise SystemExit(0 if health.available else 1)
    metadata = {}
    if args.verification_plan is not None:
        try:
            plan = json.loads(args.verification_plan)
            if not isinstance(plan, dict) or any(
                key not in {tier.value for tier in InferenceTier} or type(value) is not bool for key, value in plan.items()
            ):
                raise ValueError("Use tier names mapped to true or false.")
            metadata["verification_plan"] = plan
        except (ValueError, TypeError) as exc:
            parser.error(f"Invalid --verification-plan: {exc}")
    try:
        task = TaskRequest(task_id=args.task_id, task_type=args.task_type, metadata=metadata,
                           prompt=args.task, privacy_sensitive=args.privacy_sensitive,
                           max_cost_usd=args.max_cost_usd, max_latency_ms=args.max_latency_ms)
    except ValueError as exc:
        parser.error(str(exc))
    telemetry = TelemetryRecorder()
    try:
        kernel = AgentKernel(RuleBasedRouter(), local, MockNebiusProvider(), telemetry, max_attempts=args.max_attempts)
    except ValueError as exc:
        parser.error(str(exc))
    result = asyncio.run(kernel.execute(task))
    route = result.routing
    print(f"AgentKernel\n-----------\n\nTask:\n{task.prompt}\n\nInitial route:")
    print(f"Difficulty: {route.difficulty.value}\nRisk: {route.risk.value}\nTier: {route.selected_tier.value}")
    print(f"Provider: {route.selected_provider.value}\nConfidence: {route.confidence:.2f}")
    print(f"External knowledge required: {route.requires_external_knowledge}\nReason: {route.reason}")
    print("Verification layer: DETERMINISTIC MOCK (does not establish correctness)")
    for index, attempt in enumerate(result.attempts):
        if index:
            print(f"\nEscalating: {result.attempts[index - 1].tier.value} -> {attempt.tier.value}")
        print(f"\nAttempt {attempt.attempt_number}\nTier: {attempt.tier.value}\nProvider: {attempt.provider.value}")
        if attempt.provider == ProviderType.LOCAL_RTX:
            print(f"Backend: {attempt.metadata.get('backend', 'unknown')}\nModel: {attempt.model or '(none)'}")
        print(f"Execution: {attempt.metadata.get('execution_mode', 'unknown').upper()}\nStatus: {attempt.status.value}")
        latency_label = "simulated" if attempt.status == ExecutionStatus.MOCK else "measured"
        cost = f"${attempt.estimated_cost_usd:.4f}" if attempt.estimated_cost_usd is not None else "unknown"
        print(f"Latency ({latency_label}): {attempt.latency_ms:.1f} ms\nCloud cost: {cost}")
        print(f"Verification: {attempt.verification_status}\nReason: {attempt.verification_reason}")
        print(f"Response:\n{attempt.output_text}")
    print(f"\nFinal: {'SUCCESS' if result.success else 'FAILED'}\nAttempts: {len(result.attempts)}")
    print(f"Final tier: {result.final_tier.value if result.final_tier else '(no attempt)'}")
    print(f"Total latency (sum of inference attempts): {result.total_latency_ms:.1f} ms")
    total_cost = f"${result.total_cost_usd:.4f}" if result.total_cost_usd is not None else "unknown"
    print(f"Total cloud cost: {total_cost}\nStopped reason: {result.stopped_reason}")
    if args.telemetry_jsonl:
        print(f"Telemetry: {telemetry.export_jsonl(args.telemetry_jsonl)}")
    if not result.success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
