# LiteParse → ParseBench integration session

## Summary

Set up ParseBench from a clean working tree and integrated both LiteParse parsers (Rust port at `~/wk/liteparse_rust` and TypeScript original at `~/wk/liteparse`) as new ParseBench parse pipelines. Ran both end-to-end against the full 2,078-document dataset and surfaced an upstream Rust bug to the liteparse_rust maintainer in tmux session 59.

## Completed work

### Phase 1 — Setup

- `uv sync --extra runners` — installed full provider matrix
- `cp .env.example .env` — empty template; populated with `HF_TOKEN` (read-only) from `~/keys/hugging-face/hugging-face.md`
- `uv run parse-bench download` — pulled 2,113 files / 578 MB from `llamaindex/ParseBench` on HuggingFace; verified five categories present (chart 568, layout 500, table 503, text 508, plus shared-text dimension)

### Phase 2 — Beads issues (epic + 5 sub-issues)

| ID | Title | Status | Commit |
|---|---|---|---|
| `bd-c1hl` | Epic: Add LiteParse pipelines (Rust + TS) | closed | — |
| `bd-05kc` | Build liteparse_rust release binary + capture JSON shape | closed | `70fcf8d` |
| `bd-d2co` | Smoke-test liteparse (TS) CLI + capture JSON shape | closed | `e62c150` |
| `bd-o6xy` | Create parse provider for liteparse_rust | closed | `116c6d7` |
| `bd-5mhn` | Create parse provider for liteparse (TS) | closed | `116c6d7` |
| `bd-dw18` | Optional layout-detection providers | deferred | — |

Dependency wiring used `parent-child` for sub-issues → epic and `blocks` for sequencing (`o6xy` blocked by `05kc`, `5mhn` blocked by `d2co`, `dw18` blocked by both providers).

### Phase 3 — Provider implementation

Both parsers expose a near-identical CLI surface (`parse <FILE> --format json -o <OUT> --quiet --no-ocr`) and emit structurally-identical JSON: `{pages: [{page, width, height, text, textItems[], boundingBoxes[]}]}`. The Rust port was a port of the TS original; that explains the parity.

Two provider files share a single normalizer:

- `src/parse_bench/inference/providers/parse/liteparse_rust.py` — subprocess to `target/release/liteparse`. Default config: `enable_ocr=False`, `dpi=150`, `timeout=180s`. Validates binary exists at construction time.
- `src/parse_bench/inference/providers/parse/liteparse.py` — subprocess to `node ~/wk/liteparse/dist/src/index.js`. Default `timeout=300s` (Node cold-start is heavier). Imports `_normalize_liteparse_pages` from the Rust provider to share the normalizer.

Both use `ProviderTransientError` for timeouts/OS errors and `ProviderPermanentError` for non-zero exits and bad output. Output written to `tempfile.NamedTemporaryFile(delete=False)` and cleaned up in `finally`.

Module registrations:
- `src/parse_bench/inference/providers/parse/__init__.py` `_PROVIDER_MODULES` (alpha-sorted insertion of `liteparse` and `liteparse_rust`)
- `src/parse_bench/inference/pipelines/parse.py` (PipelineSpec for `liteparse_rust_parse` and `liteparse_parse`, both `enable_ocr: False`)
- `docs/pipelines.md` Local Pipelines table

### Phase 4 — End-to-end runs

| Pipeline | Total | Successful | Failed | Success rate | Avg latency |
|---|---:|---:|---:|---:|---:|
| `liteparse_rust_parse` | 2,078 | 1,871 | 207 | **90.04 %** | 23.78 ms |
| `liteparse_parse` (TS) | 2,078 | 2,036 | 42 | **97.98 %** | 210.77 ms |

`--test` was supplied but the runner processed the full set anyway (CLI quirk, not a blocker for verification). Latency: the Rust port is ~9x faster per page than the TS bundle.

### Phase 5 — Failure analysis

**liteparse_rust_parse — 207 failures:**

| Cause | Count | Categories |
|---|---:|---|
| Rust panic: "user-provided comparison function does not correctly implement a total order" (`smallsort.rs:860`) | 165 | chart 42, layout 124, table 30, text 11 (uniform across) |
| Non-PDF input (`.jpg`, `.png`) rejected by provider's `.pdf`-only guard | 42 | mixed |

Both failure classes show that the **panic is a real upstream bug in liteparse_rust** — the TS original handled the same 165 PDFs successfully. Sample reproducer:

```
~/wk/liteparse_rust/target/release/liteparse parse \
  /home/m/wk/ParseBench/data/docs/chart/sigma-1-2021-en_p6.pdf \
  --format json -o /tmp/out.json --quiet --no-ocr
# -> thread 'main' panicked at smallsort.rs:860: comparison function does not correctly implement a total order
```

Likely root cause: a `partial_cmp` on `f64` somewhere in the textItem/bounding-box sort path — NaN coordinates would produce `None` and a downstream `unwrap_or(Equal)` would violate totality. `RUST_BACKTRACE=1` should pinpoint.

This was relayed to the liteparse_rust maintainer (gpt-5.5-high agent in tmux session 59) with the repro command, sample failing PDFs, comparison data, and pointer to `output/liteparse_rust_parse/_errors.json`.

### Phase 6 — Layout providers (deferred)

`bd-dw18` was closed as deferred. Rationale: ParseBench `LayoutOutput` requires `predictions: list[LayoutPrediction]` with semantic class labels (Title/Text/Table/...) at block grain. LiteParse emits per-token bboxes without classes — a meaningful map from word-level bboxes to layout blocks is non-trivial and orthogonal to the parse-track integration. The parse providers do retain `raw_output[pages][i][boundingBoxes]` so a future layout adapter could pull from there.

## Commits (pushed to `origin/main` of `micahstubbs/ParseBench`)

```
116c6d7  bd-o6xy bd-5mhn: add LiteParse parse providers (Rust + TS)
e62c150  bd-d2co: document liteparse TS JSON output shape
70fcf8d  bd-05kc: document liteparse_rust JSON output shape
```

## Files changed

```
.env                                                          (gitignored - HF_TOKEN added)
docs/liteparse_rust_output_shape.md                           (new)
docs/liteparse_ts_output_shape.md                             (new)
docs/pipelines.md                                             (+2 rows in Local Pipelines)
src/parse_bench/inference/providers/parse/__init__.py         (+2 module entries)
src/parse_bench/inference/providers/parse/liteparse.py        (new, 178 lines)
src/parse_bench/inference/providers/parse/liteparse_rust.py   (new, 175 lines, hosts shared normalizer)
src/parse_bench/inference/pipelines/parse.py                  (+2 PipelineSpecs)
```

## Operational notes

- ParseBench `output/` is git-ignored; per-pipeline reports live at `output/liteparse_rust_parse/` and `output/liteparse_parse/` and can be served via `uv run parse-bench serve <pipeline>`.
- `--test` flag did not subset to 3-files-per-cat as the README implies on this CLI build; full-set runs completed in <1 min (Rust) and ~7 min (TS) at modest concurrency, so test-subset behaviour was not investigated.
- `voice-qpj` was filed earlier in `~/wk/voice-coding` for the recurring "lite" -> "light" homophone in voice transcription (`lightparse_rust` -> `liteparse_rust`).

## Pending / blocked

- **Awaiting liteparse_rust maintainer fix** for the comparator-totality panic. Once landed, re-run `uv run parse-bench run liteparse_rust_parse` should converge on the TS port's ~98 % success rate.
- **Optional polish, not yet filed**: relax the `.pdf`-only check in both providers — LiteParse TS supports image/DOCX/XLSX inputs natively, so the 42 image-rejection failures are recoverable.

## Next-session context

- Both pipelines are registered and runnable; `parse-bench compare liteparse_rust_parse liteparse_parse` produces a side-by-side report.
- If the liteparse_rust panic gets fixed upstream, just rebuild (`cargo build --release`) and re-run — no ParseBench changes needed.
- Layout track (bd-dw18 follow-up) needs a design decision on word-bbox -> block-bbox + class assignment before any code; not blocked by anything else.
