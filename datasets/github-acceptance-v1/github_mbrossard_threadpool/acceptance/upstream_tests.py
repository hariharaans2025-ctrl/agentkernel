"""Protected runner for unchanged upstream C test programs; remote only."""
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
