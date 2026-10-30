# Final benchmark

Status: running

Unknown values are null in JSON and blank in CSV. No model superiority claim is supported by this report.

| Fixture | Mode | Status | Final tier | Semantic | Sanitizer |
|---|---|---|---|---|---|
| deadlock_001 | nano_only | unresolved | NANO | Not measured | Not measured |
| deadlock_002 | nano_only | unresolved | NANO | Not measured | Not measured |
| deadlock_003 | nano_only | unresolved | NANO | Not measured | Not measured |
| deadlock_004 | nano_only | unresolved | NANO | Not measured | Not measured |
| deadlock_005 | nano_only | unresolved | NANO | Not measured | Not measured |
| race_001 | nano_only | unresolved | NANO | Not measured | Not measured |
| race_002 | nano_only | unresolved | NANO | Not measured | Not measured |
| race_003 | nano_only | unresolved | NANO | Not measured | Not measured |
| race_004 | nano_only | unresolved | NANO | Not measured | Not measured |
| race_005 | nano_only | unresolved | NANO | Not measured | Not measured |
| deadlock_001 | super_only | unresolved | SUPER | True | Not measured |
| deadlock_002 | super_only | unresolved | SUPER | False | Not measured |
| deadlock_003 | super_only | unresolved | SUPER | Not measured | Not measured |
| deadlock_004 | super_only | verified | SUPER | True | Not measured |
| deadlock_005 | super_only | unresolved | SUPER | False | Not measured |
| race_001 | super_only | verified | SUPER | True | True |
| race_002 | super_only | verified | SUPER | True | True |
| race_003 | super_only | verified | SUPER | True | True |
| race_004 | super_only | verified | SUPER | True | True |

## Aggregate metrics

```json
{
  "tasks": 19,
  "attempted_fixtures": 10,
  "bugs_diagnosed": 8,
  "diagnosis_definition": "Structured diagnosis present; correctness is not independently scored.",
  "candidate_repairs_generated": 8,
  "verified_repairs": 5,
  "verified_repair_rate": 0.2631578947368421,
  "false_fixes": 3,
  "false_fix_rate": 0.375,
  "false_fix_denominator": "Successfully applied candidates with a completed non-infrastructure verification outcome",
  "patches_rejected": 0,
  "format_rejections": 1,
  "transport_infrastructure_failures": 0,
  "verification_infrastructure_failures": 0,
  "semantic_regression_count": 2,
  "race_count": 0,
  "race_measurement": "Required/configured sanitizer campaigns only; uninstrumented zero is unknown",
  "deadlock_count": 204,
  "tooling_unavailable": 0,
  "model_calls": {
    "NANO": 10,
    "SUPER": 9,
    "ULTRA": 0
  },
  "ultra_usage": 0,
  "average_model_calls": 1.0,
  "inference_tokens": 148084,
  "token_usage_complete": true,
  "tokens_per_verified_repair": 29616.8,
  "inference_latency_ms": 128694.83260004199,
  "average_inference_latency_ms": 6773.4122421074735,
  "median_inference_latency_ms": 7248.5494000138715,
  "average_end_to_end_latency_ms": 193396.30642631795,
  "median_end_to_end_latency_ms": 29610.010600008536,
  "inference_measurement": "provider_reported_tokens_and_wall_clock_latency",
  "execution_latency_ms": 3298856.5098770484,
  "total_time_ms": 3674529.8221000414,
  "average_time_to_verified_repair_ms": 462132.914039999,
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
    "nano_only",
    "super_only",
    "ultra_only",
    "adaptive"
  ],
  "paid_calls_max_by_mode": {
    "nano_only": 10,
    "super_only": 10,
    "ultra_only": 10,
    "adaptive": 30
  },
  "paid_calls_max": 60,
  "repair_attempts_max": 50,
  "verification_stress_executions_max": 5000,
  "semantic_executions_max": 50,
  "sanitizer_verification_executions_max": 75,
  "baseline_executions_max": 180,
  "required_tsan": [
    "race_001",
    "race_002",
    "race_003",
    "race_004",
    "race_005"
  ],
  "repair_output_token_cap": 2048,
  "triage_output_token_cap": 768,
  "max_output_tokens": 110080,
  "retries": 0,
  "semantic_conditions_required": true,
  "note": "Upper bounds, not forecasts. Build failures, missing tools or successful Super verification reduce calls/executions."
}
```
