# Lessons Learned

Append-only log of non-obvious debugging insights and patterns discovered while working on ParseBench. New lessons go at the bottom; do not edit or reorganize prior entries.

---

## 2026-04-28T06:25 - Flag silently ignored when downstream of a cache check

**Problem**: `parse-bench run <pipeline> --test` and `parse-bench download --test` advertised a 3-files-per-category subset run, but processed all 2,078 examples in practice. Easy to miss because both commands "work" — they just silently use the wrong dataset.

**Root Cause**: In `pipeline/cli.py`, the `--test` flag was only consulted inside the `if not is_dataset_ready(input_path):` branch, where it controls which HuggingFace branch to download. Once `./data` had any complete dataset (full or test), `is_dataset_ready` returned True, the branch was skipped, and `--test` had nowhere to take effect. The runner read whatever was at `./data`. The `download` command had the parallel bug — it wrote the test dataset *into* the same `./data` path, so `--test` after a non-test download silently overlaid files.

**Lesson**: A flag that's only honored inside a "do X if not cached" branch becomes a no-op the second time the command runs. Any flag whose effect should persist across cache hits has to be wired into the cache-hit path too — typically by varying the cache key (here, the directory path) on the flag's value, not by gating the flag itself. The bug is invisible to first-run testing and only surfaces when developers re-run a command.

**Code Issue**:
```python
# Before — flag has no effect once dataset is downloaded
if input_dir is None:
    input_dir = "./data"
if not is_dataset_ready(input_path):
    download_dataset(data_dir=input_path, test=test)  # only place `test` is used

# After — flag changes the cache key, so the path itself differs
if input_dir is None:
    input_dir = default_data_dir(test=test)  # ./data vs ./data/test
if not is_dataset_ready(input_path):
    download_dataset(data_dir=input_path, test=test)
```

**Solution**: Routed `--test` to a separate `./data/test` subdirectory by default in all three CLI surfaces (`run`, `download`, `status`). Added a centralized `default_data_dir(test: bool)` helper so the routing stays consistent. Filed and shipped as upstream PR run-llama/ParseBench#17.

**Prevention**: When code-reviewing CLI flags, ask "does this flag still have its documented effect on the *second* invocation?" Specifically watch for flags consulted only inside `if not <cache-ready>:` branches, `try: cached except CacheMiss:` blocks, or `if force or not exists:` guards. The pattern is: a flag that controls a side effect that happens once becomes a no-op forever after.

---

## 2026-04-28T06:30 - Filing an upstream regression against a stale binary

**Problem**: Observed that previously-panicking PDFs in liteparse_rust now exit 0 but produce empty markdown. Filed bd-bvg7 ("silent-empty regression upstream") as a real regression — the panic had become silent failure. Reasoned that the upstream "fix" was masking the bug rather than addressing it.

**Root Cause**: The Rust binary at `~/wk/liteparse_rust/target/release/liteparse` had `stat -c %y` mtime of `04:38:57`, but upstream commit `edea6c4 fix(grid): use total ordering for projection sorts` landed at `04:39:51` — **53 seconds later**. The binary I was benchmarking was built before the upstream sort fix. So the "silent empty" behavior I attributed to a bad fix was probably the original bug's behavior in a different code path, not a regression at all. A simple `cargo build --release` would have resolved the question.

**Lesson**: For downstream projects that depend on a manually-built local binary, always check the binary's mtime against upstream HEAD's commit timestamp before filing an upstream bug. A surprising number of "regressions" turn out to be "I forgot to rebuild." Pre-flight check:

```bash
cd <upstream-repo>
binary_mtime=$(stat -c %Y target/release/<bin>)
head_time=$(git log -1 --format='%ct' HEAD)
test "$binary_mtime" -ge "$head_time" || echo "STALE: binary built before HEAD"
```

**Solution**: Logged this lesson here. Did not actually rebuild liteparse_rust this session — the rebuild and re-validate step was deferred to a future task (the original recommendation #1 from `/next`).

**Prevention**: When recommending a "validate the upstream fix" task, the first step has to be `cargo build --release` (or equivalent), not `parse-bench run --pipeline <X>`. Add a binary-mtime check to any reproducer-script that depends on a hand-built dependency.

---

## Meta-Lessons

- **Cache-bypass paths and flags don't compose silently.** When adding a flag to a command that has cache-aware branching, vary the cache key on the flag — don't gate the flag inside the cache-miss arm. (See 2026-04-28T06:25.)
- **Distrust your binary as much as your code.** A stale build artifact will reproduce yesterday's bug while hiding today's fix. Pre-flight every "is this fix landed?" check with a build step or an mtime check. (See 2026-04-28T06:30.)
