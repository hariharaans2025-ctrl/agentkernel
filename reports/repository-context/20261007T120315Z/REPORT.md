# Step 3: context preparation

Synthetic queue example only. No inference calls or repair-quality claim.
Counts measured with the public NVIDIA Super tokenizer and chat template. These are not confirmed Nebius billing counts.

| Context | Input tokens | Reduction vs full |
|---|---:|---:|
| full | 5299 | 0.00% |
| minified_full | 5122 | 3.34% |
| selected_grouped | 4384 | 17.27% |

Retained: complete editable source, protected caller source and header, every execution outcome and metadata, every diagnostic, complete captured stacks, verification requirements and repair instructions.
Only identical execution outcomes/diagnostics are grouped. README and Makefile text omitted from selected context; explicit build argv remains.
Full/minified/grouped prompts are saved verbatim for a future bounded A/B repair experiment. This comparison is newly constructed, not a reconstruction of prior live benchmark prompts.
Clang indexes project function definitions, references (including function pointers) and members. Retrieval conservatively follows callers/references and includes all project headers and editable files.
No claim of generic C++ dependency completeness; this sample uses known include flags. Unresolved seeds/includes fail instead of silent truncation.
Selected files: include/queue.h, src/main.c, src/queue.c.
Clang indexing/context preparation: 325.00 ms in sandbox (single observation, excludes setup/download).
Tokenizer: nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-BF16 at 2dc98e2afe4face0e4ce40972a915c45368bd34a.
No Nano/Ultra tokenizer counts, output tokens, inference latency or verified repair improvements measured. Frozen prompts and routing are unchanged.
