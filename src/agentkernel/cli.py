import argparse
import asyncio
from pathlib import Path

from agentkernel.core.models import TaskRequest
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentKernel local mock demo")
    parser.add_argument("--task", required=True)
    parser.add_argument("--task-id", default="ci_001")
    parser.add_argument("--task-type", default="ci_failure")
    parser.add_argument("--privacy-sensitive", action="store_true")
    parser.add_argument("--telemetry-jsonl", type=Path)
    args = parser.parse_args()
    task = TaskRequest(task_id=args.task_id, task_type=args.task_type,
                       prompt=args.task, privacy_sensitive=args.privacy_sensitive)
    telemetry = TelemetryRecorder()
    kernel = AgentKernel(RuleBasedRouter(), LocalRTXProvider(), MockNebiusProvider(), telemetry)
    result = asyncio.run(kernel.execute(task))
    route, inference = result.routing, result.inference
    print(f"AgentKernel\n-----------\n\nTask:\n{task.prompt}\n\nRouting decision:")
    print(f"Difficulty: {route.difficulty.value}\nRisk: {route.risk.value}\nTier: {route.selected_tier.value}")
    print(f"Provider: {route.selected_provider.value}\nConfidence: {route.confidence:.2f}")
    print(f"External knowledge required: {route.requires_external_knowledge}\nReason: {route.reason}")
    print(f"\nInference:\n{inference.output_text}\nStatus: {inference.status.value}")
    print(f"\nLatency (simulated for mocks): {inference.latency_ms:.1f} ms\nCost: ${inference.estimated_cost_usd:.4f}")
    if args.telemetry_jsonl:
        print(f"Telemetry: {telemetry.export_jsonl(args.telemetry_jsonl)}")


if __name__ == "__main__":
    main()
