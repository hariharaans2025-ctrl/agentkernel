import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.telemetry.redaction import redact
from agentkernel.config import load_env_file

from .app import ConcurrencyBugHunter, ConcurrencyPolicy
from .benchmark.evaluator import MODES, evaluate
from .benchmark.loader import load_task


def _render(job: dict) -> str:
    baseline = job["baseline"]
    counts = baseline.get("counts", {})
    verification = job.get("verification")
    lines = ["Concurrency Bug Hunter", "======================", f"Task: {job['task']}",
        f"Inference: {job['inference_mode'].upper()} | Execution: Nebius Sandbox",
        f"Baseline build: {'PASS' if baseline.get('build_passed') else 'FAIL'}",
        f"Stress campaign: {baseline.get('total_runs', 0)} runs | PASS {counts.get('PASS', 0)} | "
        f"DEADLOCK/TIMEOUT {counts.get('TIMEOUT', 0) + counts.get('POSSIBLE_DEADLOCK', 0)} | "
        f"RACE {counts.get('RACE_DETECTED', 0)} | CRASH {counts.get('CRASH', 0)}",
        "Baseline ThreadSanitizer: " + baseline.get("sanitizer", {}).get("status", "not_configured"),
        "Patterns: " + (", ".join(item["pattern"] for item in baseline.get("fingerprints", [])) or "none established"),
        "Route: " + (" -> ".join(job["route"]) or "no inference calls")]
    if verification:
        tests = verification["evidence"].get("original_tests", {})
        test_status = ("PASS" if tests.get("passed") else "FAIL") if tests.get("configured") else "not configured"
        lines.extend([f"Verification build: {'PASS' if verification['build_passed'] else 'FAIL'}",
            f"Original tests: {test_status}",
            f"Verification stress: {verification['passed_runs']}/{verification['total_runs']} PASS",
            "Verification ThreadSanitizer: " + verification["evidence"].get("sanitizer", {}).get("status", "not_run")])
    status = "VERIFIED REPAIR" if job["status"] == "verified" else job["status"].upper().replace("_", " ")
    lines.extend([f"Result: {status}", f"Reason: {job['stopped_reason']}",
        "Final tier: " + (job["route"][-1] if job["route"] else "none"),
        f"Ultra used: {'YES' if not job['ultra_avoided'] else 'NO'}",
        f"Measured execution: {job['execution_latency_ms']:.1f} ms | Total elapsed: {job['total_time_ms']:.1f} ms"])
    if job["inference_mode"] == "mock":
        lines.append("Inference tokens/latency/cost are simulated; this run does not measure model quality or pricing.")
    else:
        lines.append("Inference cost: " + (f"${job['cost_usd']:.6f}" if job["cost_usd"] is not None else "unknown (no complete configured pricing/usage)"))
    if job["status"] == "verified":
        lines.append("The patch passed the configured verification campaign. Successful runs do not prove absence of concurrency bugs.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agentkernel concurrency", description="Stress trusted C/pthreads projects; verify proposed patches through execution.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "benchmark"):
        sub = commands.add_parser(name)
        sub.add_argument("project", type=Path, help="Trusted task directory, or benchmark suite root")
        sub.add_argument("--compiler", help="Explicit gcc/clang executable; overrides trusted config compiler only")
        sub.add_argument("--static", action="store_true", help="Add -static (useful for standalone MinGW executables)")
        sub.add_argument("--stress-runs", type=int)
        sub.add_argument("--verification-runs", type=int)
        sub.add_argument("--max-attempts", type=int)
        sub.add_argument("--max-super-repairs", type=int, default=1)
        sub.add_argument("--max-ultra-repairs", type=int, default=1)
        sub.add_argument("--max-cost-usd", type=float)
        sub.add_argument("--max-latency-ms", type=int)
        sub.add_argument("--inference-mode", choices=("mock", "real"))
        sub.add_argument("--env-file", type=Path, help="Explicit private .env file; existing environment takes precedence")
        sub.add_argument("--json", action="store_true", help="Write only structured JSON to stdout")
        sub.add_argument("--json-output", type=Path)
        sub.add_argument("--telemetry-jsonl", type=Path)
        if name == "run":
            sub.add_argument("--mode", choices=MODES, default="adaptive")
    models = commands.add_parser("models", help="Explicitly contact Nebius to discover catalog model IDs")
    models.add_argument("--env-file", type=Path)
    models.add_argument("--json", action="store_true", help="Also show configured tier availability")
    probe = commands.add_parser("smoke", help="Opt-in small REAL Nebius request; never a full benchmark")
    probe.add_argument("tier", choices=("nano", "super"))
    probe.add_argument("project", nargs="?", type=Path)
    probe.add_argument("--env-file", type=Path)
    probe.add_argument("--compiler")
    probe.add_argument("--static", action="store_true")
    probe.add_argument("--json-output", type=Path)
    probe.add_argument("--telemetry-jsonl", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.env_file:
            load_env_file(args.env_file)
        if args.command == "models":
            from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider
            health = asyncio.run(NebiusTokenFactoryProvider().check_models())
            if args.json or health.error:
                data = health.model_dump()
                if not health.available and not health.error:
                    data["error"] = "configured_model_unavailable"
                print(json.dumps(redact(data), indent=2))
            else:
                print(json.dumps(redact(health.model_ids), indent=2))
            raise SystemExit(0 if health.available else 1)
        if args.command == "smoke":
            from .smoke import smoke
            if args.tier == "super" and args.project is None:
                raise ValueError("Super smoke needs a trusted fixture directory")
            task = load_task(args.project, compiler=args.compiler, static=args.static) if args.project else None
            recorder = TelemetryRecorder()
            data = redact(asyncio.run(smoke(args.tier, task=task, telemetry=recorder)))
            rendered = json.dumps(data, indent=2)
            if args.json_output:
                args.json_output.parent.mkdir(parents=True, exist_ok=True)
                args.json_output.write_text(rendered + "\n", encoding="utf-8")
            if args.telemetry_jsonl:
                recorder.export_jsonl(args.telemetry_jsonl)
            print(rendered)
            raise SystemExit(0 if data["status"] == "passed" else 1)
        if args.inference_mode:
            os.environ["AGENTKERNEL_NEBIUS_MODE"] = args.inference_mode
        policy = ConcurrencyPolicy(mode=getattr(args, "mode", "adaptive"),
            max_fixed_attempts=min(args.max_attempts,4) if args.max_attempts is not None else 1,
            allow_contract_retry=args.max_attempts is not None and args.max_attempts > 1,
            max_total_attempts=args.max_attempts if args.max_attempts is not None else int(os.getenv("AGENTKERNEL_MAX_ATTEMPTS", "4")),
            max_super_repairs=args.max_super_repairs, max_ultra_repairs=args.max_ultra_repairs,
            max_cost_usd=args.max_cost_usd, max_latency_ms=args.max_latency_ms)
        telemetry = TelemetryRecorder()
        options = dict(compiler=args.compiler, static=args.static, stress_runs=args.stress_runs, verification_runs=args.verification_runs)
        if args.command == "run":
            task = load_task(args.project, **options)
            result = asyncio.run(ConcurrencyBugHunter(telemetry=telemetry, policy=policy).run(task))
            data = result.model_dump(mode="json")
            exit_code = 0 if result.status in {"verified", "baseline_clean"} else 1
        else:
            data = asyncio.run(evaluate(args.project, policy=policy, telemetry=telemetry,
                               progress=lambda message: print(message, file=sys.stderr, flush=True), **options))
            exit_code = 1 if data.get("stopped_reason") == "host_execution_policy_blocked" else 0
        data = redact(data)
        rendered = json.dumps(data, indent=2)
        if args.json_output:
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(rendered + "\n", encoding="utf-8")
        if args.telemetry_jsonl:
            telemetry.export_jsonl(args.telemetry_jsonl)
        if args.json:
            print(rendered)
        elif args.command == "run":
            print(_render(data))
        else:
            print("Benchmark comparison (real execution; inference provenance shown below)")
            if data.get("stopped_reason"):
                print("Comparison stopped: " + data["stopped_reason"])
            for mode, value in data["modes"].items():
                metric = value["metrics"]
                print(f"{mode}: {metric['verified_repairs']}/{metric['tasks']} verified | "
                      f"false fixes {metric['false_fixes']} | tooling unavailable {metric['tooling_unavailable']} | "
                      f"inference {metric['inference_mode']}")
        raise SystemExit(exit_code)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        error = {"status": "error", "error": redact(str(exc))}
        if getattr(args, "json", False):
            print(json.dumps(error))
        else:
            print("Concurrency configuration/execution error: " + error["error"], file=sys.stderr)
        raise SystemExit(2) from None
