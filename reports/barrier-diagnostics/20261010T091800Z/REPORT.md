# Barrier diagnostic validation

Eight Clang-based regression tests passed in Nebius Sandbox. Zero model calls and inference tokens.

| Source | Barrier-with-held-mutex warnings |
|---|---:|
| original | 2 |
| failed_full | 2 |
| failed_compact | 2 |
| verified_manual | 0 |

Source locations and deterministic fingerprints are in diagnostic-results.json.
repair-context.json extends the prior compact context using only the original buggy source analysis. No known-good answer or failed candidate source is added.
The warnings are intraprocedural possible-path evidence. Aliasing, actual concurrent participants, lock return values and branch feasibility are not proved. Unsupported constructs are listed as coverage gaps. No warnings is not a safety claim.
This step adds diagnostics, not a verified model repair. The separately verified manual repair remains 100/100 stress plus semantics and 3/3 TSan; no native workload was rerun here.
Next: a new bounded Super experiment with this context, unchanged output cap and full verification. No inference was started by this validation.
