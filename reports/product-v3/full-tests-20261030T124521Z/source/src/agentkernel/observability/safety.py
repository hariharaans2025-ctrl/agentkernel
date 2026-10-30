from agentkernel.telemetry.redaction import redact

ALLOWED = set("""task_id bug_type starting_tier current_tier attempt_number route_reason model_id
baseline_runs baseline_passes baseline_deadlocks baseline_races baseline_crashes
verification_runs verification_passes verification_deadlocks verification_races verification_crashes
input_tokens output_tokens model_latency_ms retry_count finish_reason request_id verification_passed
ultra_used ultra_avoided build_success deadlock_detected race_detected regression_detected false_fix
status error_code patch_hash patch_accepted infrastructure_failures fingerprint_count execution_mode
duration_ms phase source_file_count structured_valid synthetic_evidence""".split())
FEEDBACK = {"build_success", "verification_passed", "deadlock_detected", "race_detected",
            "regression_detected", "false_fix", "ultra_used", 'patch_valid', 'compile_passed',
            'semantic_passed', 'sanitizer_passed', 'deadlocks', 'races', 'final_tier'}
ALLOWED.update(FEEDBACK)


def safe_metadata(data: dict) -> dict:
    # No prompts, model prose, source, raw logs, environment or arbitrary nested data.
    selected = {key: value[:512] if isinstance(value, str) else value for key, value in data.items()
                if key in ALLOWED and (value is None or isinstance(value, (str, bool, int, float)))}
    return redact(selected)
