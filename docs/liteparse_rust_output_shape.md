# liteparse_rust output shape

Captured 2026-04-28 from `target/release/liteparse parse` on `data/docs/table/1653739079_page40.pdf`.

## CLI invocation

```bash
~/wk/liteparse_rust/target/release/liteparse parse <FILE> --format json -o <OUTPUT.json> --quiet --no-ocr
```

Useful flags for the ParseBench provider:

| Flag | Purpose |
|---|---|
| `--format json` | Switch from default `text` to structured JSON. Required for normalization. |
| `-o <file>` | Write output to a file. Without it, prints to stdout. |
| `--quiet` / `-q` | Suppress non-error stderr noise. |
| `--no-ocr` | Disable OCR. **Required** unless built with `--features tesseract` or `--ocr-server-url` is provided — otherwise the parser warns and falls back to text-only. |
| `--dpi <int>` | Default 150. |
| `--max-pages <int>` | Default 10000. |
| `--no-precise-bbox` | Faster, less accurate bboxes. |
| `--password <pw>` | Encrypted PDFs. |

`--ocr-server-url` accepts an HTTP OCR server URL (EasyOCR/PaddleOCR-compatible per the LiteParse OCR spec).

## Cargo `tesseract` feature

Optional Cargo feature `tesseract` (uses `leptess`) enables built-in OCR. Requires system libs `libtesseract-dev` + `libleptonica-dev`. Without it, OCR must be disabled or proxied to an HTTP OCR server.

For the initial provider, ship the no-OCR variant only.

## JSON output schema

```jsonc
{
  "pages": [
    {
      "page": 0,                 // 0-indexed page number
      "width": 612.0,            // PDF point dimensions
      "height": 792.0,
      "text": "...",             // Per-page concatenated text (reading order)
      "textItems": [
        {
          "text": "...",         // Token / word / span text
          "x": 72.0,
          "y": 100.0,
          "width": 50.3,
          "height": 11.0,
          "fontName": "Helvetica"
        }
      ],
      "boundingBoxes": [          // Parallel array to textItems (same length)
        { "x1": 72.0, "y1": 100.0, "x2": 122.3, "y2": 111.0 }
      ]
    }
  ]
}
```

## Normalization to `ParseOutput`

- `markdown` = `"\n\n".join(p["text"] for p in pages)`
- Each `PageIR` = `{page_number: p["page"], width: p["width"], height: p["height"], markdown: p["text"], text_items: p["textItems"], bounding_boxes: p["boundingBoxes"]}`
- `textItems` + `boundingBoxes` are parallel arrays — preserve as auxiliary data for layout-detection scoring later.

## Errors observed

- Stderr "OCR is enabled but no OCR backend is configured…" when neither `--no-ocr` nor `--ocr-server-url` is supplied. The command still produces a valid JSON file containing text-only pages, but the warning means OCR-required pages may have empty text. **Always pass `--no-ocr` from the provider when no OCR backend is configured.**
