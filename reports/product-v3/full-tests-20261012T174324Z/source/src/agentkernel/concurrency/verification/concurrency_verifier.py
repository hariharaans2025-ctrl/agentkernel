from time import perf_counter
from collections import Counter
from typing import Any

from pydantic import BaseModel, Field

from ..campaign.manager import StressCampaignManager
from ..campaign.models import CampaignResult
from ..compile.compiler import CCompiler, Compiler
from ..instrumentation.sanitizer import SanitizerConfig, SanitizerFinding, parse_sanitizer
from ..models import ConcurrencyTask
from ..sandbox.base import SandboxBackend
from .semantics import check_semantics
from ..instrumentation.sanitizer import instrumented_task, runtime_unavailable


class ConcurrencyVerificationResult(BaseModel):
    passed: bool = False
    build_passed: bool = False
    total_runs: int = 0
    passed_runs: int = 0
    failed_runs: int = 0
    race_count: int | None = None
    deadlock_count: int = 0
    crash_count: int = 0
    infrastructure_failures: int = 0
    observed_program_failures: int = 0
    sanitizer_findings: list[SanitizerFinding] = Field(default_factory=list)
    regressions: list[str] = Field(default_factory=list)
    duration_ms: float = 0
    evidence: dict[str, Any] = Field(default_factory=dict)
    reason: str = "Verification not completed"
    execution_passed: bool | None = None
    semantic_passed: bool | None = None
    sanitizer_passed: bool | None = None
    semantic_regression: bool = False
    false_fix: bool = False


class ConcurrencyVerifier:
    def __init__(self, compiler: Compiler | None = None, campaigns: StressCampaignManager | None = None) -> None:
        self.compiler = compiler or CCompiler()
        self.campaigns = campaigns or StressCampaignManager()

    async def verify_workspace(self, task: ConcurrencyTask, sandbox: SandboxBackend,
                               baseline: CampaignResult | None = None, *, precompiled=None) -> ConcurrencyVerificationResult:
        started = perf_counter()
        result = ConcurrencyVerificationResult()
        config = task.verification_config
        build = precompiled if precompiled is not None else await self.compiler.compile(task, sandbox)
        result.build_passed = build.success
        result.evidence["build"] = build.model_dump()
        # Always require a fresh successful build: never execute a stale binary.
        if not build.success:
            result.infrastructure_failures = int(bool(build.metadata.get('error')))
            result.false_fix = not result.infrastructure_failures
            result.evidence["execution_blocked"] = build.metadata.get("execution_policy_blocked", False)
            result.reason = "Rebuild failed; no verification binary was executed."
            result.duration_ms = (perf_counter() - started) * 1000
            return result
        tests_passed = not config.required_original_tests or bool(config.original_test_commands)
        test_results = []
        original_test_regression = config.required_original_tests and not config.original_test_commands
        for command in config.original_test_commands:
            test = await sandbox.run_command(command, timeout=task.max_runtime_seconds, environment=task.environment)
            tests_passed &= test.exit_code == 0 and not test.timed_out
            if test.metadata.get("error"):
                result.infrastructure_failures += 1
            elif test.exit_code != 0 or test.timed_out:
                original_test_regression = True
            test_results.append(test.model_dump())
            if test.metadata.get("execution_policy_blocked"):
                result.evidence["execution_blocked"] = True
                result.evidence["original_tests"] = {"passed": False, "configured": True, "results": test_results}
                result.reason = "Host execution policy blocked an original test; no retry is permitted."
                result.duration_ms = (perf_counter() - started) * 1000
                return result
        result.evidence["original_tests"] = {"passed": tests_passed, "results": test_results,
                                             "configured": bool(config.original_test_commands)}
        if original_test_regression:
            result.regressions.append("Original test requirements failed")
        campaign = await self.campaigns.run(task, sandbox, runs=config.stress_runs)
        result.total_runs = len(campaign.runs)
        result.passed_runs = campaign.counts.get("PASS", 0)
        result.failed_runs = campaign.failed_runs
        result.infrastructure_failures += campaign.infrastructure_failures
        result.observed_program_failures = campaign.failed_runs - campaign.infrastructure_failures
        result.race_count = campaign.counts.get("RACE_DETECTED")
        result.deadlock_count = campaign.counts.get("TIMEOUT", 0) + campaign.counts.get("POSSIBLE_DEADLOCK", 0)
        result.crash_count = campaign.counts.get("CRASH", 0)
        result.evidence["campaign"] = campaign.compact()
        result.execution_passed = (len(campaign.runs) == config.stress_runs and result.failed_runs == 0 and tests_passed)
        if campaign.execution_blocked:
            result.evidence["execution_blocked"] = True
            result.reason = "Host execution policy blocked the verification program; no retry is permitted."
            result.duration_ms = (perf_counter() - started) * 1000
            return result
        result.sanitizer_findings = [finding for run in campaign.runs for finding in parse_sanitizer(run.stderr)]
        if baseline is not None:
            baseline_counts = Counter(run.classification.value for run in baseline.runs if not run.metadata.get("error"))
            current_counts = Counter(run.classification.value for run in campaign.runs if not run.metadata.get("error"))
            for kind, count in current_counts.items():
                if kind != "PASS" and count and not baseline_counts.get(kind):
                    result.regressions.append(f"New failure class: {kind}")
            baseline_started, current_started = sum(baseline_counts.values()), sum(current_counts.values())
            if baseline_started and current_started and (current_started - current_counts.get("PASS", 0)) / current_started > (baseline_started - baseline_counts.get("PASS", 0)) / baseline_started:
                result.regressions.append("Observed failure rate increased")
        semantic = await check_semantics(task, sandbox)
        result.evidence['semantic'] = semantic
        result.semantic_passed = semantic['passed']
        result.semantic_regression = semantic['regression']
        result.infrastructure_failures += semantic['infrastructure_failures']
        if result.semantic_regression:
            result.regressions.append('Required semantic invariant failed')
        sanitizer_ok = not config.sanitizer_required
        result.evidence["sanitizer"] = {"status": "not_configured"}
        if config.sanitizer_enabled or config.sanitizer_required:
            sanitizer = SanitizerConfig(enabled=True, required=config.sanitizer_required)
            tsan_task = instrumented_task(task)
            instrumented = await self.compiler.compile(tsan_task, sandbox, sanitizer.flags)
            if not instrumented.success:
                result.evidence["sanitizer"] = {"status": "unavailable", "build": instrumented.model_dump()}
                result.infrastructure_failures += 1
                if instrumented.metadata.get("execution_policy_blocked"):
                    sanitizer_ok = False
                    result.evidence["execution_blocked"] = True
            else:
                instrumented_campaign = await self.campaigns.run(tsan_task, sandbox, runs=config.sanitizer_runs)
                unavailable = any(runtime_unavailable(run.stderr) for run in instrumented_campaign.runs)
                sanitizer_ok = not unavailable and instrumented_campaign.failed_runs == 0 and len(instrumented_campaign.runs) == config.sanitizer_runs
                result.sanitizer_passed = None if unavailable else sanitizer_ok
                result.evidence["sanitizer"] = {"status": "passed" if sanitizer_ok else "failed",
                                                 "campaign": instrumented_campaign.compact()}
                result.sanitizer_findings.extend(finding for run in instrumented_campaign.runs for finding in parse_sanitizer(run.stderr))
                result.race_count = (result.race_count or 0) + instrumented_campaign.counts.get("RACE_DETECTED", 0) if not unavailable else result.race_count
                result.infrastructure_failures += instrumented_campaign.infrastructure_failures
                if unavailable:
                    result.evidence['sanitizer']['status'] = 'unavailable'
                    result.infrastructure_failures += 1
                else:
                    result.observed_program_failures += instrumented_campaign.failed_runs - instrumented_campaign.infrastructure_failures
                if instrumented_campaign.execution_blocked:
                    result.evidence["execution_blocked"] = True
        unknown_failures = result.failed_runs - (campaign.counts.get("RACE_DETECTED", 0) + result.deadlock_count + result.crash_count)
        result.passed = (tests_passed and sanitizer_ok and semantic['required_passed'] and not result.infrastructure_failures and not result.regressions and unknown_failures == 0
                         and len(campaign.runs) == config.stress_runs
                         and (result.race_count or 0) <= config.allowed_races and result.deadlock_count <= config.allowed_deadlocks
                         and result.crash_count <= config.allowed_crashes)
        result.reason = ("The patch passed the configured verification campaign." if result.passed else
                         "The patch failed the configured verification campaign; inspect execution evidence.")
        result.duration_ms = (perf_counter() - started) * 1000
        result.false_fix = not result.passed and not result.infrastructure_failures and not result.evidence.get('execution_blocked', False)
        return result
