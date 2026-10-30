# Frozen prompting policy: additional holdout evaluation

The frozen few-shot policy verified 3/4 fresh programs; zero-shot verified 2/4. Each arm produced one false fix. Few-shot used 3.04 times the tokens, and approximately 2.03 times the tokens per verified repair. The improvement extended to one additional net repair, but was not consistent across cases.

| Metric | Zero-shot | Frozen few-shot |
|---|---:|---:|
| Model calls / retries | 4 / 0 | 4 / 0 |
| Verified repairs | 2/4 | 3/4 |
| False fixes rejected by verifier | 1 | 1 |
| Invalid proposals rejected before execution | 1 | 0 |
| Unknown outcomes | 0 | 0 |
| Total tokens including failed attempts | 8,879.0 | 26,987.0 |
| Tokens per verified repair | 4,439.5 | 8,995.7 |
| Total inference latency | 76.90 s | 30.45 s |
| Total end-to-end latency | 181.29 s | 163.90 s |
| Median inference latency | 16.39 s | 6.98 s |
| Median verification latency | 28.47 s | 27.54 s |
| Median end-to-end latency | 49.46 s | 40.38 s |

Verification medians use three executed zero-shot candidates and four few-shot candidates. The zero-shot invalid proposal never reached execution: its verification latency is null, not an invented zero. The aggregate zero-shot verification total is therefore null; three observed verification durations sum to 86.60 s, compared with 110.92 s for all four few-shot candidates. End-to-end totals include all eight attempts and setup overhead. Reference calibration is excluded from evaluation latency.

| Fresh program | Zero-shot | Frozen few-shot |
|---|---|---|
| pair_snapshot | VERIFIED | Rejected: 0/100 stress, semantic failure, 3 detected TSan races |
| inventory_balance | Rejected: 0/100 stress, semantic failure, 3 detected TSan races | VERIFIED |
| nested_credit | VERIFIED | VERIFIED |
| empty_queue_return | Invalid edit: filename outside allowlist | VERIFIED |

All five model candidates marked VERIFIED passed compilation, 100/100 stress executions, protected original tests, the semantic oracle, and 3/3 TSan executions. Both failed applied candidates were rejected by the mandatory verifier. No failed candidate was deployed or counted as a success. Invalid output is a separate failure category, not a false fix under the existing metric definition.

The few-shot snapshot proposal split the update critical section around sched_yield and left the reader unprotected. The zero-shot inventory proposal moved reads outside the locks and retained inconsistent guards. These are observed failing proposals, not repaired by a follow-up call.

## Frozen method

- Model: `Qwen/Qwen3-30B-A3B-Instruct-2507`; temperature 0; 2,048 output-token cap; one call per case per arm; no correction calls, retries, training, or substitution.
- The exact successful pilot system message, user-prompt prefix/schema, training examples, and model settings were retained. Only the new original program context changes.
- The selection rule uses a coarse family label fixed before model evaluation: shared_state selects race_002 and race_003; liveness selects deadlock_004 and job_queue. These are curator-supplied labels, not an evaluated automatic classifier.
- All eight exact request payloads and their hashes were saved before reference calibration and before any target-model request. Model-call order alternates the first arm across fixtures. No prompt or selection adaptation followed an outcome.
- Reference repairs are stored exclusively in calibration evidence. They were never inserted into model messages or training data. Original defective sources and protected workload code are visible to the model in both arms.
- Both race baselines produced three TSan race detections; both liveness baselines timed out three times. Every reference passed the full 100-stress/semantics/3-TSan gate. This establishes tested solvability, not model success.
- Existing source, benchmark evidence, prior datasets, frozen policy, payloads, calibration evidence, and input files passed the post-evaluation hash check.

## Cost

The pre-run inference bound was $0.2146304 for eight calls, including a conservative reservation of the full advertised input context per call. Sandbox incremental charges are $0 based on the user's free-beta confirmation. Calculated inference cost from actual provider token usage and catalog rates was **$0.0044626**. This is a usage calculation, not an invoice. No training was submitted.

Zero-shot consumed 5,606 input + 3,273 output tokens; few-shot consumed 25,880 input + 1,107 output tokens. The shorter few-shot responses accompanied lower observed inference time, but these individual API durations also include provider/network variation; they do not establish a stable speedup.

## Interpretation and limits

The four-case extension gives a modest observed gain (3/4 versus 2/4), with one regression on a case the base prompt solved. Few-shot solved two cases zero-shot did not, lost one, and tied on one verified success. It did not improve false-fix count and increased tokens per verified repair from 4,439.5 to 8,995.7. This supports further evaluation of the frozen policy, not an unconditional rollout or a decision to fine-tune.

These are four newly authored, small C/pthreads programs, not large real repositories. They were not previously used for this project's target-model calls or training; absence from base-model pretraining cannot be proven. Shared bug families and synchronization idioms remain related to the training examples. The workload oracle is a tested acceptance contract, not proof of correctness for all possible schedules or inputs. Four observations cannot establish statistical superiority.

The earlier two-case pilot was used to select this prompting policy and is kept separate from this fresh evaluation. Its 0/2 versus 2/2 result is not pooled into a new unbiased estimate. These four cases are now evaluated; any further policy tuning based on their results requires another untouched holdout.

## Evidence

- [Frozen prompt and selection policy](frozen-policy.json)
- [Payload freeze and predeclared cases](payload-freeze.json)
- [Evaluation plan](plan.json)
- [Aggregate results](results.json)
- [Integrity check](integrity.json)
- Each case directory contains the raw model response, patch or rejection, metrics, and all executed verification batches. Calibration references remain in the separate calibration directory.
