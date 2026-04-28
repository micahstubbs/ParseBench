# Drop `.pdf`-only guard in LiteParse providers

## Summary

Removed the suffix check in both LiteParse parse providers (Rust port + TS original) that was rejecting non-PDF inputs upfront. Both underlying CLIs accept image (`.png`/`.jpg`) and Office (DOCX/XLSX/PPTX) formats; the provider-level `.pdf`-only guard was failing 42/2078 image inputs in ParseBench (all in the layout group). Re-ran both pipelines and confirmed the 42 image rejections are now 0-quality successes instead of inference errors.

While re-running, also discovered that the 165 prior Rust panics (`smallsort.rs:860` totality violation) no longer reproduce — they exit 0 instead — but produce empty markdown rather than real text. Filed `bd-bvg7` to track the silent-failure regression upstream.

## Completed work

### Beads issues

| ID | Title | Status |
|---|---|---|
| `bd-o7nl` | Epic: Drop .pdf-only guard in LiteParse providers (recover 42 image inputs) | open (parent) |
| `bd-37cs` | Drop .pdf-only suffix check in liteparse_rust provider | closed in `64bb9d1` |
| `bd-cngk` | Drop .pdf-only suffix check in liteparse (TS) provider | closed in `64bb9d1` |
| `bd-s09p` | Re-run pipelines + refresh leaderboard | done in this session, ready to close |
| `bd-bvg7` | liteparse_rust silently returns empty markdown on previously-panicking PDFs | open (upstream) |

Dependency wiring: `bd-37cs` and `bd-cngk` as parent-child of `bd-o7nl`; `bd-s09p` blocked by both code-fix issues.

### Pre-fix smoke probe

Confirmed both CLIs accept images directly with `--no-ocr`:

| Probe | Exit | Output bytes | Page text |
|---|---:|---:|---|
| `liteparse parse layout/16968.png --no-ocr` (Rust) | 0 | 161 | empty (schema-valid) |
| `liteparse parse layout/89955590.jpg --no-ocr` (Rust) | 0 | 186 | empty (schema-valid) |
| `node liteparse/.../index.js parse 16968.png --no-ocr` (TS) | 0 | 157 | empty (schema-valid) |
| `node liteparse/.../index.js parse 89955590.jpg --no-ocr` (TS) | 0 | 164 | empty (schema-valid) |

TS `--help` advertises "PDF, DOCX, XLSX, PPTX, images, etc." The dataset only contains `.pdf`/`.png`/`.jpg` (2,037/23/19), so DOCX/XLSX/PPTX support is unverified but accepted by removing the guard.

### Code change

Single commit, both providers modified the same way:

```diff
-        pdf_path = Path(request.source_file_path)
-        if pdf_path.suffix.lower() != ".pdf":
-            raise ProviderPermanentError(f"Only .pdf files supported, got {pdf_path.suffix}")
-        if not pdf_path.exists():
-            raise ProviderPermanentError(f"PDF file not found: {pdf_path}")
+        source_path = Path(request.source_file_path)
+        if not source_path.exists():
+            raise ProviderPermanentError(f"Source file not found: {source_path}")
```

Plus internal `pdf_path` → `source_path` renames in `_build_command` and the timeout error message. Existing non-zero-returncode handler covers any input the underlying CLI doesn't actually accept (it'll raise `ProviderPermanentError` from the CLI's own diagnostic).

Files: `src/parse_bench/inference/providers/parse/liteparse.py`, `src/parse_bench/inference/providers/parse/liteparse_rust.py`. Lint clean (`ruff check`). Imports OK.

### Re-run results

Inference success counts:

| Pipeline | Before | After | Δ |
|---|---:|---:|---:|
| `liteparse_rust_parse` | 1,871 / 2,078 (90.04%) | **2,078 / 2,078 (100%)** | +207 |
| `liteparse_parse` (TS) | 2,036 / 2,078 (97.98%) | **2,078 / 2,078 (100%)** | +42 |

The Rust pipeline gained 207, not just the 42 image inputs — the 165 prior `smallsort.rs:860` panics also no longer reproduce (verified by direct re-test of `chart/sigma-1-2021-en_p6.pdf`). Latest `~/wk/liteparse_rust` HEAD is `16f4e72`; the binary at `target/release/liteparse` was rebuilt at 04:38 (between the original full sweep and this session).

### Silent-failure regression in liteparse_rust

The 165 prior-panic PDFs now succeed at the inference layer but produce empty markdown:

```
chart/sigma-1-2021-en_p6.pdf:
  liteparse_rust md_len = 0     (was: panic)
  liteparse (TS) md_len = 3740  (unchanged, baseline)
table/0000027_page1.pdf:
  liteparse_rust md_len = 0
  liteparse (TS) md_len = 18,697
```

Filed `bd-bvg7` upstream. The fix appears to swallow the partial_cmp totality violation rather than address it (NaN coords from PDF text extraction → returning Equal → silently producing no textItems). Caller-visible behavior went from "loud panic" to "silent empty" — strictly worse for observability. Suggested fix: either correct the comparator (probably gate on `f.is_nan()` and skip those textItems) or, at minimum, surface a non-zero exit + diagnostic stderr.

### Per-dimension scores (post-refresh, both pipelines)

| Dimension | Rust avg_rule_pass_rate | TS avg_rule_pass_rate |
|---|---:|---:|
| chart | 0.000 | 0.000 |
| text_content | 0.003 | 0.630 |
| text_formatting | 0.000 | 0.029 |
| table (grits_con) | 0.000 | 0.000 |
| layout | 64/500 evaluated (rest blocked by bd-dw18 LayoutOutput-required) | same |

The Rust port's near-zero text scores vs TS's 0.63 on text_content are a direct consequence of the silent-empty regression. Without that, Rust should match TS roughly (both hit the same data via the same pipeline; TS is just JS-on-Node for the same algorithm).

## Commits

```
64bb9d1  bd-37cs bd-cngk: drop .pdf-only guard in LiteParse providers
```

## Files changed

```
src/parse_bench/inference/providers/parse/liteparse.py        (-3 / +2 net)
src/parse_bench/inference/providers/parse/liteparse_rust.py   (-3 / +2 net)
```

`output/` is git-ignored; per-pipeline reports refreshed locally at `output/{liteparse_rust_parse,liteparse_parse}/_evaluation_report_dashboard.html` and the cross-pipeline `output/_leaderboard.html`.

## Pending / blocked

- **`bd-bvg7`** — silent-empty regression in liteparse_rust. Belongs upstream; ParseBench provider needs no further changes.
- **`bd-dw18`** — layout-detection adapter for LiteParse remains deferred. Word-bbox → block-bbox + class assignment design still required.

## Next-session context

- Both LiteParse pipelines now process all 2,078 documents end-to-end.
- TS port is the practical baseline for any Rust-port quality comparison until `bd-bvg7` is resolved upstream.
- `parse-bench compare liteparse_rust_parse liteparse_parse` will quantify the silent-empty gap (Rust's 0-byte outputs vs TS's real markdown on the same PDFs).
- ParseBench has no project-local `.beads/`; all related issues live in the global beads (`~/.beads/beads.db`).
