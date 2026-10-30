# Step 4: full versus compact context

One synthetic job-queue example, one Super attempt per arm. Fixed order: full then selected/grouped.
Calls reserved: 2/2. Known tokens: 10844. Stop reason: completed.
Protected source and evidence unchanged: True.

| Arm | Outcome | Input tokens | Output tokens | Provider wall seconds | Verification seconds | End-to-end seconds |
|---|---|---:|---:|---:|---:|---:|
| full | rejected | 5299 | 612 | 5.619 | 254.001 | 273.763 |
| selected_grouped | rejected | 4384 | 549 | 5.264 | 250.812 | 263.560 |

Provider wall latency includes the model-catalog check. Verification includes build, original tests, stress, semantics and TSan. End-to-end includes workspace setup and cleanup.
Actual input/output tokens are provider-reported. Unavailable costs remain null. Incomplete jobs are unknown, not failures.
One pair cannot establish statistical superiority or general repair-quality preservation. No Nano/Ultra routing experiment was performed.
The full verification contract is unchanged: original tests, 100 stress runs, semantic oracle, 3 required TSan runs. Invalid/unapplied proposals are not verified.
Experimental batching was used identically in both arms; production defaults are unchanged. Candidate files are saved as artifacts, not applied to the example project.
A token reservation is checked before calls. Unknown usage or reservation overruns stop subsequent calls; the ceiling is not proof of exact provider tokenization before a response.
