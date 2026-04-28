# liteparse (TypeScript) output shape

Captured 2026-04-28 from `node ~/wk/liteparse/dist/src/index.js parse` on `data/docs/table/1653739079_page40.pdf`.

## CLI invocation

```bash
node /home/m/wk/liteparse/dist/src/index.js parse <FILE> --format json -o <OUTPUT.json> --quiet --no-ocr
```

The TS bundle binary `lit` is also exposed via `npm i -g @llamaindex/liteparse`, but for hermetic ParseBench runs prefer the explicit `node …/dist/src/index.js` form so we don't depend on global install state.

## Flags

Identical CLI surface to liteparse_rust (intentional — Rust is a port of this TS version). Same flag set:

| Flag | Notes |
|---|---|
| `--format json` | Required for normalization. Default is `text`. |
| `-o <file>` | Required to capture structured output to disk. |
| `--quiet` / `-q` | Suppress progress noise on stdout. |
| `--no-ocr` | Disable OCR. Default is on, falls back to bundled `tesseract.js` if no `--ocr-server-url`. |
| `--ocr-server-url <url>` | Optional external OCR HTTP endpoint. |
| `--ocr-language <lang>` | Default `en`. |
| `--dpi <int>` | Default 150. |
| `--max-pages <int>` | Default 10000. |
| `--target-pages <ranges>` | e.g. `1-5,10,15-20`. |

For the initial provider, default to `--no-ocr` (matches the Rust provider default — tesseract.js initialization is slow and not needed for native-text PDFs).

## JSON output schema

**Structurally identical to liteparse_rust** — same top-level `pages[]` array with `page/width/height/text/textItems[]/boundingBoxes[]`. Differences:

- Per-token fields: TS includes additional `fontSize` and `confidence` fields (Rust port omits them).
- `textItems` and `boundingBoxes` are still parallel arrays of equal length.

```jsonc
{
  "pages": [
    {
      "page": 0,
      "width": 612,
      "height": 792,
      "text": "...",
      "textItems": [
        {
          "text": "...",
          "x": 72.0,
          "y": 100.0,
          "width": 50.3,
          "height": 11.0,
          "fontName": "Helvetica",
          "fontSize": 11.0,
          "confidence": 1.0
        }
      ],
      "boundingBoxes": [
        { "x1": 72.0, "y1": 100.0, "x2": 122.3, "y2": 111.0 }
      ]
    }
  ]
}
```

## Normalization

Same as liteparse_rust:

- `markdown` = `"\n\n".join(p["text"] for p in pages)`
- `PageIR` per page from `{page, width, height, text, textItems, boundingBoxes}`
- Extra TS-only fields (`fontSize`, `confidence`) are preserved as auxiliary data, not used for parse-track scoring.

## Provider strategy

Because the JSON shapes match, a single shared normalizer can be lifted into a helper module and called from both `liteparse_rust.py` and `liteparse.py` providers. For the initial integration, copy-paste the normalizer into both providers (DRY refactor as a follow-up if both providers ship and stay in tree).
