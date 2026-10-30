# Final benchmark

Status: completed

Unknown values are null in JSON and blank in CSV. No model superiority claim is supported by this report.

| Fixture | Mode | Status | Final tier | Semantic | Sanitizer |
|---|---|---|---|---|---|
| deadlock_001 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| deadlock_002 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| deadlock_003 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| deadlock_004 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| deadlock_005 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| race_001 | ultra_only | verified | ULTRA | True | True |
| race_002 | ultra_only | verified | ULTRA | True | True |
| race_003 | ultra_only | verified | ULTRA | True | True |
| race_004 | ultra_only | verified | ULTRA | True | True |
| race_005 | ultra_only | unresolved | ULTRA | Not measured | Not measured |
| deadlock_001 | adaptive | verified | SUPER | True | Not measured |
| deadlock_002 | adaptive | unresolved | ULTRA | False | Not measured |
| deadlock_003 | adaptive | unresolved | NANO | Not measured | Not measured |
| deadlock_004 | adaptive | verified | SUPER | True | Not measured |
| deadlock_005 | adaptive | verified | SUPER | True | Not measured |
| race_001 | adaptive | unresolved | NANO | Not measured | Not measured |
| race_002 | adaptive | verified | SUPER | True | True |
| race_003 | adaptive | verified | SUPER | True | True |
| race_004 | adaptive | verified | SUPER | True | True |
| race_005 | adaptive | unresolved | NANO | Not measured | Not measured |

## Aggregate metrics

```json
{
  "tasks": 20,
  "attempted_fixtures": 10,
  "bugs_diagnosed": 11,
  "diagnosis_definition": "Structured diagnosis present; correctness is not independently scored.",
  "candidate_repairs_generated": 11,
  "verified_repairs": 10,
  "verified_repair_rate": 0.5,
  "false_fixes": 1,
  "false_fix_rate": 0.09090909090909091,
  "false_fix_denominator": "Successfully applied candidates with a completed non-infrastructure verification outcome",
  "patches_rejected": 0,
  "format_rejections": 0,
  "transport_infrastructure_failures": 0,
  "verification_infrastructure_failures": 0,
  "semantic_regression_count": 1,
  "race_count": 0,
  "race_measurement": "Required/configured sanitizer campaigns only; uninstrumented zero is unknown",
  "deadlock_count": 100,
  "tooling_unavailable": 0,
  "model_calls": {
    "NANO": 10,
    "SUPER": 7,
    "ULTRA": 11
  },
  "ultra_usage": 11,
  "average_model_calls": 1.4,
  "inference_tokens": 207565,
  "token_usage_complete": true,
  "tokens_per_verified_repair": 20756.5,
  "inference_latency_ms": 191572.86530002602,
  "average_inference_latency_ms": 9578.643265001301,
  "median_inference_latency_ms": 9584.963849993073,
  "average_end_to_end_latency_ms": 143903.86337000382,
  "median_end_to_end_latency_ms": 207506.66650000494,
  "inference_measurement": "provider_reported_tokens_and_wall_clock_latency",
  "execution_latency_ms": 2459638.3691078657,
  "total_time_ms": 2878077.2674000766,
  "average_time_to_verified_repair_ms": 221643.5067500046,
  "cost_usd": null,
  "cost_per_verified_repair_usd": null,
  "inference_mode": "real"
}
```

## Execution gate

```json
{
  "fixtures": 10,
  "modes": [
    "ultra_only",
    "adaptive"
  ],
  "paid_calls_max_by_mode": {
    "ultra_only": 10,
    "adaptive": 30
  },
  "paid_calls_max": 40,
  "repair_attempts_max": 30,
  "verification_stress_executions_max": 3000,
  "semantic_executions_max": 30,
  "sanitizer_verification_executions_max": 45,
  "baseline_executions_max": 90,
  "required_tsan": [
    "race_001",
    "race_002",
    "race_003",
    "race_004",
    "race_005"
  ],
  "repair_output_token_cap": 2048,
  "triage_output_token_cap": 768,
  "max_output_tokens": 69120,
  "retries": 0,
  "semantic_conditions_required": true,
  "note": "Upper bounds, not forecasts. Build failures, missing tools or successful Super verification reduce calls/executions."
}
```
