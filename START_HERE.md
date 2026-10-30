# AgentKernel handoff — 22 October 2026

Private console: https://agentkernel-control.abuzzleaf32.chatgpt.site/

AgentKernel connects C/C++ repositories to model-generated repair proposals and independent execution in Nebius Sandbox. A repair is accepted only after the configured original tests, 100 stress executions, semantic checks, and three ThreadSanitizer executions pass. Accepted means the configured checks passed; it is not a proof that all possible bugs are absent.

## Connect in ChatGPT

The private Site exposes eight AgentKernel tools through its Sites-created plugin. Open **Plugins → Personal → Created by you**, find AgentKernel, then Install or Connect. If the plugin is already installed but its tools do not appear, start a new chat. The native installation card supplied with this handoff uses the exact published plugin identity.

Try: “List my AgentKernel codebases”, “Show the latest repair and its verification evidence”, or “Prepare a repair for my inventory codebase using Adaptive v2.” Preparing a repair does not call a model. ChatGPT must show you the exact source scope, contract and charge ceiling before starting it. The approval review expires after five minutes and can be used once. Signed-in access is required; no API keys belong in chat.

Tools: status, list codebases, list runs, get run, prepare repair, start approved repair, connect a public GitHub codebase, and cancel a queued request. New work still requires the workspace agent; the plugin does not make the local model or credentials permanently cloud-hosted.

## What is included

- **Source archive:** Python controller, hosted console source, tests, fixtures, datasets, examples, and startup tools. No credentials or installed dependencies.
- **Evidence archive:** a read-only copy of saved experiments and validation results. Historical absolute paths document the original run; do not rewrite those records or treat reference/manual repairs as model successes.
- **Adapter archive:** the trained LoRA adapter, tokenizer/config, training records, and active-model pointer. Base weights are separate; they are approximately 3.1 GB and already cached on the original computer.
- **Release manifest:** file hashes, archive hashes, and validation status. Archives extract under an `agentkernel/` directory. Extract the adapter into the same parent as the source to add its `models/` folder.

## Start on Windows

1. Extract the source ZIP and open PowerShell in its `agentkernel` folder.
2. Run `./Setup-Project.ps1` with Python 3.11 or later installed. This installs controller dependencies only.
3. Edit `.env` privately using `.env.example` as the template. Configure Nebius API key, project ID, exact model IDs and the sandbox image. Never put keys in the frontend or a shared archive.
4. Run `./Start-Console-Agent.ps1`. Enter the private Site service token at its hidden prompt. The foreground agent holds it in memory; stop it with Ctrl+C. Only one agent may run per workspace.
5. Open the private console. Connect a public GitHub repository, choose its project folder, and supply `agentkernel.repository.json`. The included job queue and pair-snapshot demos work without historical report files.
6. Review the editable/protected file list, commands, model, and current cost ceiling. Start the repair, inspect its patch and evidence, then download the result for review. Nothing is merged automatically.

The service token belongs to the existing owner-private Site and is deliberately excluded from the release. Ask Codex to reconnect the existing Site if you need a fresh connection. Another account needs its own private Sites deployment; the source manifest identifies this owner's Site.

Keep the computer and connection agent running for new jobs. The website stays hosted when the agent is offline, but cannot execute work. C/C++ compilation and verification stay in Nebius Sandbox. The optional specialist performs model inference on the local GPU; it does not execute the proposed C/C++ program locally. Public GitHub imports are supported; private GitHub authentication is not implemented.

## Optional fine-tuned specialist

Hosted Nano/Super/Ultra/Qwen calls do not require local model weights. For the adaptive route, extract the adapter archive, create `.training-venv`, install the pinned `requirements-training.txt` and a compatible CUDA PyTorch runtime, and run `scripts/restore_specialist_base.py` with that runtime if the base cache is missing. This downloads the pinned model revision without starting training. See `ADAPTIVE_UPGRADE.md` for the tested runtime and measured results.

The website's adaptive v2 route is **fine-tuned specialist → Super → Ultra**, stopping after verification succeeds. It allows up to three calls, including two hosted fallback calls, within its reviewed cost and token limits. Invalid output or a rejected candidate may escalate; infrastructure failures and unknown outcomes stop. This differs from the historical frozen Nano-triage benchmark, whose evidence remains unchanged. Experimental adaptive v3 modules in the source are separate from the published v2 flow.

## Costs and evidence

No new model calls or training are needed to install this release. A future repair can incur hosted inference charges. The UI uses live prices, a per-request ceiling of $0.25, and the existing pilot budget ledger. Sandbox beta access was previously confirmed free by the owner; confirm your own billing if deploying under another account.

Do not replace the original workspace's `reports/sites-console/state.json` with a fresh copy: it tracks spending and unknown calls. The source archive intentionally does not include an active queue or ledger. A fresh installation starts a separate pilot ledger; it is not an account-wide billing authority. Do not run multiple copied workspaces against one budget.

The final two-case specialist evaluation measured 0/2 base repairs, 1/2 fine-tuned repairs and 1/2 adaptive repairs. The barrier case remains unresolved. A separate website-triggered inventory run passed all gates. These small synthetic-suite results do not establish production reliability or statistical superiority.

## Validation

Consult the adjacent `release-manifest.json` for this release's actual checks. The full account-independent test suite runs using `scripts/push_sandbox.py` in Nebius Sandbox; it excludes live paid-provider/GPU account tests and records skips explicitly. Windows cannot run the compiler/symlink-dependent suite directly. Type checking and the frontend build run locally. Existing live repair evidence is preserved; packaging does not replay interrupted jobs.
