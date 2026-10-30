# Verified repair learning pilot

Prepared: 6 deduplicated verified training targets, 1 development-validation target,
and 2 newly authored held-out programs. Every training target is linked to its
original source and recorded verification evidence. Reconstructed edit outputs
were applied locally as text and checked against the saved verified candidate.
Faulty or unreplayable model attempts were excluded rather than trained as successes.

Both held-out reference repairs passed 100 stress executions, protected original
tests, semantic checks, and 3 TSan executions in Nebius Sandbox. References are
not included in inference messages or training upload files. These are verifier
calibration results, not model-repair results. No target-model evaluation has run.

The training corpus is a small seed pilot, not evidence that fine-tuning will help.
The proposed model is Qwen/Qwen3-30B-A3B-Instruct-2507, documented for LoRA and
present in the live catalog. Fine-tuning access returned HTTP 200.

Training is NOT submitted. The user authorized a US$10 pilot; current documentation
says tuned models deploy through dedicated endpoints. No bounded training-plus-
hosting quote was available, so no unpriced training or deployment job was started.
Before submission, obtain a quote or enforceable spending cap for training and
evaluation hosting, and measure sequences with the selected model's tokenizer.
Do not silently truncate long examples, increase the budget, or upload the test set.

Evaluation metrics remain null until real runs exist. Use evaluation-protocol.json
for matched base/tuned comparisons. Failed-attempt tokens count toward tokens per
verified repair. Zero verified repairs makes that metric undefined, not zero.
The verifier remains mandatory after training, regardless of model confidence.

Provider sources:
- https://docs.tokenfactory.nebius.com/post-training/models
- https://docs.tokenfactory.nebius.com/post-training/datasets
- https://docs.tokenfactory.nebius.com/post-training/how-to-fine-tune

Existing benchmark and prior evidence files are unchanged.
