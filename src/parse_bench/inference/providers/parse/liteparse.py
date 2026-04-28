"""Provider for the TypeScript LiteParse (subprocess invocation via node)."""

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from parse_bench.inference.providers.base import (
    Provider,
    ProviderConfigError,
    ProviderPermanentError,
    ProviderTransientError,
)
from parse_bench.inference.providers.parse.liteparse_rust import _normalize_liteparse_pages
from parse_bench.inference.providers.registry import register_provider
from parse_bench.schemas.parse_output import ParseOutput
from parse_bench.schemas.pipeline import PipelineSpec
from parse_bench.schemas.pipeline_io import (
    InferenceRequest,
    InferenceResult,
    RawInferenceResult,
)
from parse_bench.schemas.product import ProductType


@register_provider("liteparse")
class LiteparseProvider(Provider):
    """Provider for the TypeScript LiteParse (npm @llamaindex/liteparse).

    Shells out to `node <dist>/index.js parse …`. Captures structured JSON
    output and normalizes per-page text into ParseOutput. No API key required.
    """

    DEFAULT_CLI_COMMAND = [
        "node",
        str(Path.home() / "wk" / "liteparse" / "dist" / "src" / "index.js"),
    ]

    def __init__(self, provider_name: str, base_config: dict[str, Any] | None = None):
        """
        :param base_config:
            - `cli_command`: list[str] command prefix
              (default ['node', '~/wk/liteparse/dist/src/index.js'])
            - `enable_ocr`: bool (default False). When False, passes --no-ocr.
            - `ocr_server_url`: optional HTTP OCR server URL.
            - `ocr_language`: default 'en'.
            - `dpi`: int (default 150).
            - `timeout`: subprocess timeout in seconds (default 300 — Node
              cold-start + tesseract.js init is slower than the Rust binary).
        """
        super().__init__(provider_name, base_config)
        cli_command = self.base_config.get("cli_command")
        self._cli_command: list[str] = (
            list(cli_command) if cli_command else list(self.DEFAULT_CLI_COMMAND)
        )
        self._enable_ocr = bool(self.base_config.get("enable_ocr", False))
        self._ocr_server_url = self.base_config.get("ocr_server_url")
        self._ocr_language = self.base_config.get("ocr_language", "en")
        self._dpi = int(self.base_config.get("dpi", 150))
        self._timeout = int(self.base_config.get("timeout", 300))

        # Validate the CLI dispatch is callable: the second element is the
        # script path when invoking node directly. Tolerate other shapes.
        if (
            len(self._cli_command) >= 2
            and self._cli_command[0] == "node"
            and not Path(self._cli_command[1]).is_file()
        ):
            raise ProviderConfigError(
                f"liteparse TS bundle not found at {self._cli_command[1]}. "
                f"Build with: cd ~/wk/liteparse && npm install && npm run build"
            )

    def _build_command(self, source_path: str, output_path: str) -> list[str]:
        cmd = [
            *self._cli_command,
            "parse",
            source_path,
            "--format",
            "json",
            "-o",
            output_path,
            "--dpi",
            str(self._dpi),
            "--quiet",
        ]
        if not self._enable_ocr:
            cmd.append("--no-ocr")
        elif self._ocr_server_url:
            cmd.extend(["--ocr-server-url", self._ocr_server_url])
            cmd.extend(["--ocr-language", self._ocr_language])
        else:
            cmd.extend(["--ocr-language", self._ocr_language])
        return cmd

    def run_inference(self, pipeline: PipelineSpec, request: InferenceRequest) -> RawInferenceResult:
        if request.product_type != ProductType.PARSE:
            raise ProviderPermanentError(
                f"LiteparseProvider only supports PARSE, got {request.product_type}"
            )

        source_path = Path(request.source_file_path)
        if not source_path.exists():
            raise ProviderPermanentError(f"Source file not found: {source_path}")

        started_at = datetime.now()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            output_path = tmp.name

        try:
            cmd = self._build_command(str(source_path), output_path)
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as e:
                raise ProviderTransientError(
                    f"liteparse (TS) timed out after {self._timeout}s on {source_path}"
                ) from e
            except OSError as e:
                raise ProviderTransientError(f"Failed to invoke liteparse: {e}") from e

            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                stdout = (proc.stdout or "").strip()
                raise ProviderPermanentError(
                    f"liteparse (TS) exited {proc.returncode}: {stderr or stdout or '<no output>'}"
                )

            if not Path(output_path).is_file():
                raise ProviderPermanentError(
                    f"liteparse (TS) produced no output file at {output_path}"
                )

            try:
                with open(output_path) as f:
                    raw_output = json.load(f)
            except json.JSONDecodeError as e:
                raise ProviderPermanentError(
                    f"liteparse (TS) produced invalid JSON: {e}"
                ) from e

            completed_at = datetime.now()
            latency_ms = int((completed_at - started_at).total_seconds() * 1000)

            return RawInferenceResult(
                request=request,
                pipeline=pipeline,
                pipeline_name=pipeline.pipeline_name,
                product_type=request.product_type,
                raw_output=raw_output,
                started_at=started_at,
                completed_at=completed_at,
                latency_in_ms=latency_ms,
            )
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

    def normalize(self, raw_result: RawInferenceResult) -> InferenceResult:
        if raw_result.product_type != ProductType.PARSE:
            raise ProviderPermanentError(
                f"LiteparseProvider only supports PARSE, got {raw_result.product_type}"
            )

        pages, full_text = _normalize_liteparse_pages(raw_result.raw_output)

        output = ParseOutput(
            task_type="parse",
            example_id=raw_result.request.example_id,
            pipeline_name=raw_result.pipeline_name,
            pages=pages,
            markdown=full_text,
        )

        return InferenceResult(
            request=raw_result.request,
            pipeline_name=raw_result.pipeline_name,
            product_type=raw_result.product_type,
            raw_output=raw_result.raw_output,
            output=output,
            started_at=raw_result.started_at,
            completed_at=raw_result.completed_at,
            latency_in_ms=raw_result.latency_in_ms,
        )
