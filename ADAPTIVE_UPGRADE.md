# AgentKernel adaptive upgrade

The private website is ready: https://agentkernel-control.abuzzleaf32.chatgpt.site/.
The trained specialist is installed and the background connection agent is running.

## Use it

Open Overview, choose `inventory_stock` and `Adaptive v2 | Fine-tuned > Super > Ultra`, review the contract and current charge ceiling, then start the repair. Verification and Route show the full result; Evaluation shows the training identity and matched comparison. Export evidence or download the patch for review.

The computer and connection agent must remain running for new jobs. The website stays privately hosted. Original repository files are preserved. Interrupted repair jobs are never replayed automatically.

## Actual training

- Base: Qwen/Qwen2.5-Coder-1.5B-Instruct, revision `2e1fd397ee46e1388853d2af2c993145b0f1098a`.
- CUDA LoRA training on the NVIDIA GeForce RTX 5050 Laptop GPU; 18,464,768 trainable parameters.
- Rank 16, alpha 32, dropout 0.05, BF16, learning rate 0.0003.
- 8 verified training programs and 1 separate development-validation program. Historical examples retain their recorded verification contracts and provenance.
- 8 epochs, epoch 7 selected using development loss only. Final training took 73.29 seconds with cached weights, excluding setup and earlier pilots.
- Development assistant loss: 0.136868 to 0.054168. This measures fit, separately from repair success.
- Adapter SHA-256: `48127afc2c0ed2f988313c5acd9c919eb28b8eb9c25f6d77ccbf9ef1c48c18a6`.

The model emits raw C inside file markers. The controller converts this into an exact-source patch and rejects extra files, protected-file changes and changed scheduling-hook counts.

## Final matched test

Two fresh synthetic programs were frozen before evaluation: an inventory reservation race and a barrier/mutex deadlock. Neither final test target entered training or checkpoint selection. Earlier pilot programs are development-seen and are excluded from final unseen counts.

| Arm | Verified | Tokens including failures | Hosted inference |
| --- | --- | --- | --- |
| Base specialist | 0 / 2 | 1,075 | $0 |
| Fine-tuned specialist | 1 / 2 | 1,041 | $0 |
| Adaptive route | 1 / 2 | 13,304 | $0.0129878 |

The inventory repair passed compilation, original tests, 100/100 stress runs, the protected semantic oracle, all 3 ThreadSanitizer runs, and scheduling-hook preservation.

The barrier deadlock remains unresolved. The local model returned unchanged source, Super returned an incomplete response, and Ultra reached the output cap. The controller rejected all three. Manual reference repairs were used only to calibrate the verifier, never counted as model successes.

A separate website-triggered inventory run also passed every gate: one local model call, 502 tokens, no paid fallback, $0 hosted inference, 91.61 seconds end to end.

This is a two-case synthetic transfer pilot within familiar bug families. It does not establish production generalization, statistical superiority, or absence of unobserved concurrency bugs.

## Route and costs

The route is local fine-tuned specialist, then Super, then Ultra. It stops at the first fully verified repair. Invalid responses and rejected candidates may escalate. Infrastructure failures and unknown outcomes stop the route. Each candidate starts from the same frozen original source.

Limits: at most 3 calls, including at most 2 paid calls; 2,048 output tokens per call; a reviewed live-price ceiling no greater than $0.25; and a 1,800-second deadline. The installed cases allow 150,144 total tokens and 48,000 input tokens per call. The local specialist also has an 8,192-token complete-context limit. Unknown paid usage retains its reservation.

Final comparison cost: $0.0129878. Across all three training/development pilots in this upgrade: $0.0598827 hosted inference. Earlier unrelated console runs are recorded separately. No hosted training job was purchased. Local GPU electricity was not measured. Remote execution used the previously confirmed free Sandbox beta.

22 controller tests passed remotely. One historical seeding test was excluded because its earlier private fixture paths are absent from the remote test snapshot. The website passed TypeScript checking and its production build. The live run tested the browser queue, connection agent, model, remote execution and evidence display together.

## Recovery and deliverables

Existing project:
`C:\Users\HARI HARAAN\Documents\Codex\2026-09-14\files-pasted-by-the-user-you\outputs\agentkernel`

- Active pointer: `models/active-specialist.json`.
- Trained adapter: `models/adaptive-specialist-v3/adapter`.
- Base weights: `models/adaptive-specialist-v2/base`, cached separately.
- Training dataset: `datasets/adaptive-v2/pilot-v3`.
- Final cases: `datasets/adaptive-v2/holdout-v3`.
- Final comparison: `reports/adaptive-v2/evaluation-20261012T163615Z`.
- Verifier calibration: `reports/adaptive-v2/holdout-validation-20261012T163243Z`.
- Controller checks: `reports/adaptive-v2/unit-tests-20261012T163849Z`.
- Website test: `reports/sites-console/runs/2c402840-71de-4ce2-a684-0e67dc7a9d75`.

The trained-adapter ZIP contains real LoRA weights, tokenizer/config and training records. It requires the separately cached pinned base model. The source ZIP is an overlay for the existing project, not a standalone deployment. Credentials and environment files are excluded.

The background connection agent is PID 1328. After restarting the computer, reconnect using `node scripts/start_sites_agent.mjs` from the project and supply a fresh private Sites service token through the hidden prompt. No token is stored on disk. Codex can reconnect the existing private site.

## Reproduce explicitly

Run these from the existing configured project. Adaptive runs can make paid fallback calls.

```powershell
# Installed fine-tuned case: no hosted model charge.
.\.venv\Scripts\python.exe scripts\run_adaptive_repair.py --case inventory_stock --mode fine_tuned

# Bounded adaptive route, using current live prices.
.\.venv\Scripts\python.exe scripts\run_adaptive_repair.py --case inventory_stock --mode adaptive --max-cost-usd 0.25

# Train into a new directory; existing artifacts are preserved.
.\.training-venv\Scripts\python.exe scripts\train_local_specialist.py --dataset datasets\adaptive-v2\pilot-v3 --out models\adaptive-specialist-new --base-cache models\adaptive-specialist-v2\base --epochs 8

# A repeated comparison uses already-seen cases.
.\.venv\Scripts\python.exe scripts\evaluate_adaptive_pilot.py --data datasets\adaptive-v2\holdout-v3 --model-root models\adaptive-specialist-v3
```

The tested training runtime uses Python 3.14.7, PyTorch 2.11.0+cu128 and the pinned `requirements-training.txt`. The current machine already has the runtime and weights installed.

Private deployment: `appgdep_6acd0ea1d2a4819192ded400b7239254`.
Published source: `436efc0703c7a0575c9238a3fa66d35179cdc0dc`.
