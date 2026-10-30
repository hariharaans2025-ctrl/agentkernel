from pathlib import Path

from agentkernel.core.enums import ExecutionStatus
from agentkernel.core.models import AttemptRecord, InferenceResult, TaskRequest, VerificationResult
from agentkernel.verification.base import Verifier
from agentkernel.observability import span

from ..campaign.models import CampaignResult
from ..models import ConcurrencyTask
from ..repair.patch_parser import parse_repair, validation_details
from ..repair.prompts import TriageSummary
from ..sandbox.local import safe_path
from ..sandbox.nebius import NebiusSandboxBackend
from .concurrency_verifier import ConcurrencyVerifier
from ..compile.compiler import CCompiler


class TriageVerifier(Verifier):
    async def verify(self, task: TaskRequest, inference: InferenceResult,
                     attempt_history: list[AttemptRecord]) -> VerificationResult:
        if inference.status == ExecutionStatus.FAILED:
            return VerificationResult(passed=False, retryable=inference.metadata.get("retryable", True),
                                      reason="Triage inference unavailable.", evidence={"error": inference.metadata.get("error_code")},
                                      verifier_name="triage_contract")
        try:
            if len(inference.output_text) > 16000 or inference.status == ExecutionStatus.FAILED:
                raise ValueError("Invalid inference")
            triage = TriageSummary.model_validate_json(inference.output_text)
            baseline = task.metadata["concurrency_context"]["baseline"]
            if triage.failed_runs != baseline["failed_runs"] or (triage.pass_runs is not None and triage.pass_runs != baseline["total_runs"] - baseline["failed_runs"]):
                raise ValueError("Counts contradict runtime evidence")
            valid_ids = {run["run_id"] for run in baseline["representative_runs"]}
            if not set(triage.representative_runs) <= valid_ids:
                raise ValueError("Unknown representative run")
            return VerificationResult(passed=True, reason="Structured triage validated against execution counts.",
                                      evidence=triage.model_dump(), verifier_name="triage_contract")
        except ValueError as exc:
            return VerificationResult(passed=False, reason="Malformed triage. Return only the specified JSON schema, exact observed counts and valid run IDs.",
                                      retryable=not (attempt_history and attempt_history[-1].verification_evidence.get("error_code") == "invalid_model_output"),
                                      evidence={"error_code": "invalid_model_output", "validation_errors": validation_details(exc)},
                                      verifier_name="triage_contract")


class RepairVerifier(Verifier):
    def __init__(self, concurrency_task: ConcurrencyTask, baseline: CampaignResult,
                 temporary_parent: Path | None = None) -> None:
        self.task, self.baseline, self.temporary_parent = concurrency_task, baseline, temporary_parent
        self.results: list[dict[str, object]] = []

    async def verify(self, task: TaskRequest, inference: InferenceResult,
                     attempt_history: list[AttemptRecord]) -> VerificationResult:
        if inference.status == ExecutionStatus.FAILED:
            return VerificationResult(passed=False, reason="Inference failed; no patch was applied.",
                                      retryable=False, evidence={"error": inference.metadata.get("error_code")}, verifier_name="concurrency_campaign")
        try:
            sources = {name: safe_path(self.task.workspace, name).read_text(encoding="utf-8")
                       for name in self.task.source_files}
            proposal = parse_repair(inference.output_text, sources)
        except ValueError as exc:
            return VerificationResult(passed=False, reason="Invalid repair JSON or source edits. Return the requested edit contract using exact ORIGINAL source blocks; inspect validation_errors.",
                                      retryable=False if task.metadata.get('bounded_concurrency') and not task.metadata.get('allow_contract_retry') else not (attempt_history and attempt_history[-1].verification_evidence.get("error_code") == "invalid_model_output"),
                                      evidence={"error_code": "invalid_model_output", "validation_errors": validation_details(exc)},
                                      verifier_name="concurrency_campaign")
        async with NebiusSandboxBackend(temporary_parent=self.temporary_parent) as sandbox:
            await sandbox.upload_project(self.task.workspace, self.task.source_files + self.task.support_files)
            async with span('patch'), span("patch_application", current_tier=inference.tier.value, attempt_number=len(attempt_history) + 1) as observed:
                applied = await sandbox.apply_patch(proposal.patch, self.task.source_files)
                observed.update(patch_accepted=applied.success, patch_hash=applied.patch_hash)
            entry: dict[str, object] = {"tier": inference.tier.value, "proposal": proposal.model_dump(),
                                        "patch": applied.model_dump(), 'false_fix': False}
            if not applied.success:
                self.results.append(entry)
                return VerificationResult(passed=False, reason="Patch rejected: " + (applied.error or "unknown"),
                                          retryable=not task.metadata.get('bounded_concurrency', False) or bool(task.metadata.get('allow_contract_retry')),
                                          evidence=applied.model_dump(), verifier_name="concurrency_campaign")
            async with span('compile') as observed:
                build = await CCompiler().compile(self.task, sandbox)
                observed.update(build_success=build.success)
                await observed.feedback(compile_passed=build.success)
            async with span('verification'), span("verification_campaign", current_tier=inference.tier.value) as observed:
                verified = await ConcurrencyVerifier().verify_workspace(self.task, sandbox, self.baseline, precompiled=build)
                verified.duration_ms += build.duration_ms
                observed.update(verification_runs=verified.total_runs, verification_passes=verified.passed_runs,
                    verification_deadlocks=verified.deadlock_count, verification_races=verified.race_count,
                    verification_crashes=verified.crash_count, infrastructure_failures=verified.infrastructure_failures,
                    duration_ms=verified.duration_ms, verification_passed=verified.passed)
                await observed.feedback(build_success=verified.build_passed, verification_passed=verified.passed,
                    deadlock_detected=verified.deadlock_count > 0, race_detected=verified.race_count > 0 if verified.race_count is not None else None,
                    regression_detected=bool(verified.regressions),
                    false_fix=verified.false_fix)
            entry["verification"] = verified.model_dump(mode="json")
            entry['false_fix'] = verified.false_fix
            entry['candidate_sources'] = {name: safe_path(sandbox.workspace, name).read_text(encoding='utf-8') for name in self.task.source_files}
            async with span('feedback') as observed:
                await observed.feedback(patch_valid=True, compile_passed=verified.build_passed,
                    semantic_passed=verified.semantic_passed, sanitizer_passed=verified.sanitizer_passed,
                    verification_passed=verified.passed, false_fix=verified.false_fix,
                    deadlocks=verified.deadlock_count, races=verified.race_count if verified.sanitizer_passed is not None else None)
            self.results.append(entry)
            return VerificationResult(passed=verified.passed, reason=verified.reason,
                                      retryable=not verified.evidence.get("execution_blocked", False) and not verified.infrastructure_failures,
                                      evidence={"patch_hash": applied.patch_hash, 'patch_application': applied.model_dump(),
                                                'candidate_sources': entry['candidate_sources'], 'source_basis': 'Next edits must target the original source; failed candidate is evidence only.',
                                                "verification": verified.model_dump(mode="json")},
                                      verifier_name="concurrency_campaign")
