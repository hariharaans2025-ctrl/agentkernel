"""Freeze two public, pinned C/pthreads codebases and calibrate remotely.

Git acquisition never checks out or executes hooks, LFS, submodules or project
code locally. All compiler/test execution uses the configured Nebius sandbox.
These are unmodified upstream sources, NOT seeded bugs or training examples.
"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile

from agentkernel.config import load_env_file
from agentkernel.concurrency.compile.compiler import CCompiler
from agentkernel.concurrency.instrumentation.sanitizer import SanitizerConfig, instrumented_task
from agentkernel.concurrency.models import ConcurrencyTask
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.onboarding import create_plan
from agentkernel.repository.product_campaign import ProductCampaign


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "datasets/github-acceptance-v1"
PROJECTS = [
    {"id": "github_mbrossard_threadpool", "url": "https://github.com/mbrossard/threadpool",
     "revision": "9f7df71c1274fbb6af5a25a1d190044d9c1eda08", "source": "src/threadpool.c",
     "header": "src/threadpool.h", "license": "BSD-2-Clause"},
    {"id": "github_pithikos_threadpool", "url": "https://github.com/Pithikos/C-Thread-Pool",
     "revision": "2b56942a7347280ea4d0ede238cefacef96db4bb", "source": "thpool.c",
     "header": "thpool.h", "license": "MIT"},
]


HARNESS = r'''#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <pthread.h>
#include <sched.h>
HEADER
enum { JOBS = 256, PRODUCERS = 2 };
static _Atomic int seen[JOBS];
static _Atomic int completed;
static _Atomic long sum;
static int identities[JOBS];
static POOL_TYPE pool;
static void execute(void *arg) {
    int id = *(int *)arg;
    if (id < 0 || id >= JOBS) abort();
    sched_yield();
    if (atomic_fetch_add(&seen[id], 1) != 0) abort();
    atomic_fetch_add(&sum, id + 1);
    atomic_fetch_add(&completed, 1);
}
static void *produce(void *arg) {
    int lane = *(int *)arg;
    for (int id = lane; id < JOBS; id += PRODUCERS) {
        identities[id] = id;
        SUBMIT
    }
    return NULL;
}
int main(void) {
    for (int round = 0; round < 2; round++) {
        for (int i = 0; i < JOBS; i++) atomic_store(&seen[i], 0);
        atomic_store(&completed, 0); atomic_store(&sum, 0);
        INIT
        if (!pool) return 11;
        int lanes[PRODUCERS]; pthread_t threads[PRODUCERS];
        for (int i = 0; i < PRODUCERS; i++) {
            lanes[i] = i;
            if (pthread_create(&threads[i], NULL, produce, &lanes[i])) return 12;
        }
        for (int i = 0; i < PRODUCERS; i++) if (pthread_join(threads[i], NULL)) return 13;
        WAIT_DESTROY
        if (atomic_load(&completed) != JOBS || atomic_load(&sum) != (long)JOBS * (JOBS + 1) / 2) return 14;
        for (int i = 0; i < JOBS; i++) if (atomic_load(&seen[i]) != 1) return 15;
    }
    puts("PASS SEMANTIC_PASS: 512 jobs exactly once; concurrent producers; safe repeated shutdown");
    return 0;
}
'''


UPSTREAM_RUNNER = r'''"""Protected runner for unchanged upstream C test programs; remote only."""
import concurrent.futures, json, pathlib, subprocess, sys, time
kind = sys.argv[1]
if kind == "mbrossard":
    tests = [("tests/shutdown.c", [], None), ("tests/thrdtest.c", [], None), ("tests/heavy.c", [], None)]
    library, includes = "src/threadpool.c", ["-Isrc"]
else:
    # Preserve the upstream C files. Bound arguments instead of the shell suite's
    # 1,000-worker/100,000-job load, and exclude unavailable Valgrind checks.
    tests = [("tests/src/api.c", [], None), ("tests/src/conc_increment.c", ["2000", "4"], "2000"),
             ("tests/src/no_work.c", ["4"], None), ("tests/src/nonzero_heap_stack.c", [], None),
             ("tests/src/wait.c", ["8", "4", "0", "0"], None), ("tests/src/pause_resume.c", ["4"], "SLEPT")]
    library, includes = "thpool.c", ["-I."]
pathlib.Path("acceptance/binaries").mkdir(exist_ok=True)
def check(item):
    source, args, expected = item
    binary = "acceptance/binaries/" + pathlib.Path(source).stem
    started = time.monotonic()
    build = subprocess.run(["gcc", "-std=gnu11", "-O1", "-g", "-pthread", *includes, library, source, "-o", binary],
                           capture_output=True, text=True, timeout=12)
    if build.returncode: return {"source":source,"passed":False,"phase":"build","stderr":build.stderr[-4096:]}
    result = subprocess.run(["./"+binary,*args],capture_output=True,text=True,timeout=12)
    elapsed = time.monotonic() - started
    ok = result.returncode == 0 and (expected is None or expected in result.stdout)
    if source.endswith("pause_resume.c"): ok = ok and 6 <= elapsed <= 10
    return {"source":source,"passed":ok,"exit_code":result.returncode,"duration_seconds":elapsed,
            "stdout":result.stdout[-4096:],"stderr":result.stderr[-4096:]}
try:
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as workers: results = list(workers.map(check,tests))
except Exception as exc:
    print(json.dumps({"passed":False,"error":type(exc).__name__})); sys.exit(1)
passed = all(row["passed"] for row in results)
print(json.dumps({"passed":passed,"results":results,"scope":"unchanged upstream C tests, bounded documented arguments"}))
sys.exit(0 if passed else 1)
'''


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)


def git_source(project):
    git = shutil.which("git") or r"C:\Program Files\Git\bin\git.exe"
    cache = ROOT / "work/github-acceptance-v1" / project["id"]
    cache.parent.mkdir(parents=True, exist_ok=True)
    hooks = cache.parent / "disabled-hooks"; hooks.mkdir(exist_ok=True)
    environment = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                   "GIT_TERMINAL_PROMPT": "0", "GIT_LFS_SKIP_SMUDGE": "1"}
    options = [git, "-c", "core.hooksPath="+str(hooks), "-c", "credential.helper=",
               "-c", "filter.lfs.process=", "-c", "filter.lfs.smudge=", "-c", "filter.lfs.required=false"]
    def run(args):
        result = subprocess.run(options+args, env=environment, capture_output=True, timeout=60)
        if result.returncode: raise RuntimeError("Pinned public Git acquisition failed; no project code executed")
        return result.stdout
    if not cache.exists(): run(["init", "--bare", str(cache)])
    run(["--git-dir="+str(cache), "fetch", "--depth=1", "--no-tags", project["url"]+".git", project["revision"]])
    revision = run(["--git-dir="+str(cache), "rev-parse", "FETCH_HEAD"]).decode().strip()
    if revision != project["revision"]: raise ValueError("Pinned revision mismatch")
    if sum(p.stat().st_size for p in cache.rglob("*") if p.is_file()) > 5_000_000:
        raise ValueError("Public source clone exceeds bounded 5 MB acquisition")
    archive = run(["--git-dir="+str(cache), "archive", "--format=zip", project["revision"]])
    if len(archive) > 5_000_000: raise ValueError("Public source archive exceeds bounded size")
    return zipfile.ZipFile(io.BytesIO(archive))


def prepare():
    if DATA.exists():
        manifest = json.loads((DATA/"manifest.json").read_text(encoding="utf-8"))
        for case in manifest["cases"]:
            for name, sha in case["file_sha256"].items():
                if hashlib.sha256((DATA/case["id"]/name).read_bytes()).hexdigest() != sha:
                    raise ValueError("Frozen GitHub acceptance source changed")
        return manifest
    DATA.mkdir(parents=True, exist_ok=False)
    records = []
    for project in PROJECTS:
        folder = DATA/project["id"]; folder.mkdir()
        with git_source(project) as archive:
            for item in archive.infolist():
                if item.is_dir(): continue
                path = PurePosixPath(item.filename)
                if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts): raise ValueError("Unsafe public archive path")
                # Keep only visible source/doc/test files; Git/CI internals are not uploaded.
                if any(part.startswith(".") for part in path.parts): continue
                if item.file_size > 2_000_000: raise ValueError("Oversized public source file")
                target = folder.joinpath(*path.parts); target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(archive.read(item))
        harness = HARNESS
        if "mbrossard" in project["id"]:
            replacements = {"HEADER": '#include "src/threadpool.h"', "POOL_TYPE":"threadpool_t *",
                            "INIT":"pool = threadpool_create(4, 128, 0);",
                            "SUBMIT":"int rc; while ((rc = threadpool_add(pool, execute, &identities[id], 0)) == threadpool_queue_full) sched_yield(); if (rc != 0) abort();",
                            "WAIT_DESTROY":"if (threadpool_destroy(pool, threadpool_graceful) != 0) return 16;"}
            kind, include = "mbrossard", "-Isrc"
        else:
            replacements = {"HEADER": '#include "thpool.h"', "POOL_TYPE":"threadpool",
                            "INIT":"pool = thpool_init(4);",
                            "SUBMIT":"if (thpool_add_work(pool, execute, &identities[id]) != 0) abort();",
                            "WAIT_DESTROY":"thpool_wait(pool); thpool_destroy(pool);"}
            kind, include = "pithikos", "-I."
        for token, value in replacements.items(): harness = harness.replace(token,value)
        (folder/"acceptance").mkdir()
        (folder/"acceptance/semantics.c").write_text(harness,encoding="utf-8",newline="")
        (folder/"acceptance/upstream_tests.py").write_text(UPSTREAM_RUNNER,encoding="utf-8",newline="")
        description = ("Preserve this public thread-pool implementation's API, license and original tests. "
                       "Two concurrent producers submit 256 uniquely identified jobs to four workers; every callback must execute exactly once, "
                       "with correct totals. Repeat pool creation and complete graceful/waited destruction safely. "
                       "Repair observed races, invalid mutex lifecycle, deadlock or lost work without removing functional work or synchronization. "
                       "Only the listed implementation source is editable; headers, upstream tests and acceptance harness are protected.")
        source = [project["source"]]
        support = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.relative_to(folder).as_posix() not in source)
        command = ["gcc","-std=gnu11","-pthread","-g","-O1",include,"-I.",project["source"],"acceptance/semantics.c","-o","acceptance_app"]
        verification = {"required_build_success":True,"stress_runs":100,"required_original_tests":True,
                        "original_test_commands":[["python3","acceptance/upstream_tests.py",kind]],
                        "sanitizer_enabled":True,"sanitizer_required":True,"sanitizer_runs":3,"sanitizer_compiler":"clang",
                        "semantic_checks":[{"name":"512 unique callbacks exactly once across concurrent producers and repeated safe pool shutdown",
                                            "build_command":command,"run_command":["./acceptance_app"],"expected_stdout":"SEMANTIC_PASS","required":True}]}
        contract = {"schema_version":1,"project":project["id"],"description":description,"origin":"user_repository",
                    "source_files":source,"support_files":support,"build_command":command,"run_command":["./acceptance_app"],
                    "binary_path":"acceptance_app","expected_behavior":"PASS","compile_timeout_seconds":30,"max_runtime_seconds":15,"baseline_runs":3,
                    "verification":verification,"budgets":{"max_model_calls":3,"max_total_tokens":160000,"max_input_tokens_per_call":48000,
                    "max_output_tokens_per_call":8192,"max_wall_seconds":1800},"execution_backend":"nebius","max_upload_bytes":20000000}
        write_json(folder/"contract.json",contract)
        plan = create_plan(folder,folder/"contract.json",folder/"plan")
        task = plan["task"];task["metadata"].update(fixture_description=description,github_url=project["url"],git_revision=project["revision"],seeded_regression=False,split="public-github-acceptance-v1")
        write_json(folder/"task.json",task)
        hashes = {name:row["sha256"] for name,row in plan["files"].items()}
        record = {**project,"source_files":source,"support_files":support,"file_sha256":hashes,"upload_bytes":plan["upload_bytes"],
                  "plan_sha256":plan["plan_sha256"],"seeded_regression":False,"source_modified":False,"model_calls":0,
                  "scope":"unchanged public upstream implementation; protected original C tests plus custom semantics"}
        write_json(folder/"provenance.json",record); records.append(record)
    manifest = {"schema_version":1,"cases":records,"frozen_utc":datetime.now(timezone.utc).isoformat(),"model_calls":0,
                "training_use":False,"seeded_regression":False,"claim":"Public repository acceptance, not proof of arbitrary-codebase correctness.",
                "limitations":["Public code may have appeared in base-model pretraining; no claim of pretraining exclusion.",
                               "Pithikos original C tests use bounded documented arguments; Valgrind and 1,000-worker shell loads are outside this acceptance scope."]}
    write_json(DATA/"manifest.json",manifest)
    return manifest


async def calibrate(manifest):
    load_env_file(ROOT/".env")
    os.environ["AGENTKERNEL_SANDBOX_IMAGE"] = "agentkernel-clang:20261003122908"
    out = ROOT/"reports/product-v3/github-calibration"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out.mkdir(parents=True,exist_ok=False);write_json(out/"started.json",{"model_calls":0,"automatic_replay":False,"cases":[r["id"] for r in manifest["cases"]]})
    rows=[]
    for case in manifest["cases"]:
        folder=out/case["id"];folder.mkdir()
        task=ConcurrencyTask.model_validate({**json.loads((DATA/case["id"]/"task.json").read_text()),"workspace":DATA/case["id"]})
        print("Calibrating public upstream",case["id"],flush=True)
        try:
            async with NebiusSandboxBackend() as box:
                await box.upload_project(task.workspace,task.source_files+task.support_files)
                build=await CCompiler().compile(task,box);write_json(folder/"baseline-build.json",build.model_dump(mode="json"))
                if not build.success: raise RuntimeError("Upstream acceptance harness did not compile")
                campaign=ProductCampaign(folder,batch_cap=20,stop_on_failure=False)
                verified=await ConcurrencyVerifier(campaigns=campaign).verify_workspace(task,box,precompiled=build)
                write_json(folder/"upstream-verification.json",verified.model_dump(mode="json"))
                row={"case":case["id"],"github_url":case["url"],"git_revision":case["revision"],"seeded_regression":False,
                     "baseline_clean":verified.passed,"original_tests_passed":verified.evidence.get("original_tests",{}).get("passed"),
                     "stress_passed":verified.passed_runs,"stress_total":verified.total_runs,"semantic_passed":verified.semantic_passed,
                     "tsan_passed":verified.sanitizer_passed,"sanitizer_findings":len(verified.sanitizer_findings),
                     "infrastructure_failures":verified.infrastructure_failures,"model_calls":0,"verification_ms":verified.duration_ms}
        except Exception as exc:
            row={"case":case["id"],"status":"unknown","error":type(exc).__name__,"model_calls":0,"automatic_replay":False}
        rows.append(row);write_json(folder/"summary.json",row)
        print(json.dumps(row),flush=True)
    write_json(out/"complete.json",{"cases":rows,"model_calls":0,"paid_inference_usd":0,"origin":"upstream verifier calibration, not model repair success"})
    print("GitHub calibration saved",out,flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--prepare-only",action="store_true");args=parser.parse_args()
    frozen=prepare()
    print("Frozen public acceptance tasks:",DATA,flush=True)
    if not args.prepare_only: asyncio.run(calibrate(frozen))
