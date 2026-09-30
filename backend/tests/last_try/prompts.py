#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pipeline.py — convert a raw Majles (Iranian Parliament) legal bill text
file into the structured JSON schema described in prompts.py, using an LLM.

The document is split into hierarchical chunks (header / one per ماده /
admin opinions) instead of fixed-size chunks, each chunk is sent to the
LLM in parallel with a SHARED, cached system prompt, and the per-chunk
JSON fragments are merged back into one document plus a metadata block
recording how it was produced.

Examples
--------
Anthropic:
    python pipeline.py --input hormuz1.txt --output hormuz1.json \\
        --provider anthropic --model claude-sonnet-4-6 --workers 4

Any OpenAI-compatible endpoint (OpenAI itself, Azure, OpenRouter, a local
vLLM/Ollama server, ...):
    python pipeline.py --input bill.txt --output bill.json \\
        --provider openai-compatible --model gpt-4.1 \\
        --base-url https://openrouter.ai/api/v1 --api-key "$OPENROUTER_API_KEY"
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from chunker import Chunk, chunk_legal_document
from prompts import SYSTEM_PROMPT
from providers import build_provider

FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)


def build_user_message(chunk: Chunk) -> str:
    lines = [
        f"chunk_type: {chunk.chunk_type}",
        f"chunk_id: {chunk.chunk_id}",
    ]
    if chunk.article_number:
        lines.append(f"article_number: {chunk.article_number}")
    lines.append("raw_text:")
    lines.append('"""')
    lines.append(chunk.text)
    lines.append('"""')
    lines.append("Return ONLY the JSON object for this chunk. No markdown fences, no commentary.")
    return "\n".join(lines)


def parse_json_response(raw_text: str) -> Dict[str, Any]:
    cleaned = FENCE_RE.sub("", raw_text.strip()).strip()
    return json.loads(cleaned)


def process_chunk(provider, chunk: Chunk, max_retries: int = 2) -> Dict[str, Any]:
    """Call the LLM for one chunk, retrying on malformed JSON output."""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        resp = provider.complete(SYSTEM_PROMPT, build_user_message(chunk))
        try:
            data = parse_json_response(resp.text)
            return {
                "chunk_id": chunk.chunk_id,
                "chunk_type": chunk.chunk_type,
                "order": chunk.order,
                "data": data,
                "metadata": {
                    "model": resp.model,
                    "input_tokens": resp.input_tokens,
                    "output_tokens": resp.output_tokens,
                    "cached_tokens": resp.cached_tokens,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "attempts": attempt + 1,
                },
            }
        except json.JSONDecodeError as e:
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"chunk {chunk.chunk_id} produced invalid JSON after {max_retries + 1} attempt(s): {last_err}")


def _article_sort_key(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 10_000


def merge_results(results: List[Dict[str, Any]], *, source_file: str, provider_name: str, model: str) -> Dict[str, Any]:
    results_sorted = sorted(results, key=lambda r: r["order"])
    merged: Dict[str, Any] = {"سند": {}}
    articles: List[dict] = []
    usage_totals = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0}

    for r in results_sorted:
        data, meta = r["data"], r["metadata"]
        for k in usage_totals:
            usage_totals[k] += meta.get(k) or 0

        if r["chunk_type"] == "header":
            for k, v in data.items():
                if k not in ("chunk_type", "chunk_id"):
                    merged["سند"][k] = v
        elif r["chunk_type"] == "article":
            art = data.get("ماده")
            if art:
                articles.append(art)
        elif r["chunk_type"] == "admin":
            for k, v in data.items():
                if k not in ("chunk_type", "chunk_id"):
                    merged["سند"][k] = v

    if articles:
        merged["سند"].setdefault("متن_ماده_واحده", {})
        merged["سند"]["متن_ماده_واحده"]["ماده"] = sorted(articles, key=lambda a: _article_sort_key(a.get("شماره")))

    merged["_pipeline_metadata"] = {
        "source_file": source_file,
        "provider": provider_name,
        "model": model,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "chunk_count": len(results_sorted),
        "token_usage_total": usage_totals,
        "chunks": [
            {
                "chunk_id": r["chunk_id"],
                "chunk_type": r["chunk_type"],
                "order": r["order"],
                **r["metadata"],
            }
            for r in results_sorted
        ],
    }
    return merged


def run(args: argparse.Namespace) -> None:
    text = Path(args.input).read_text(encoding="utf-8")
    doc_id = hashlib.sha1(str(args.input).encode()).hexdigest()[:8]
    chunks = chunk_legal_document(text, doc_id=doc_id)

    provider = build_provider(args.provider, args.model, api_key=args.api_key, base_url=args.base_url)

    print(f"[pipeline] {len(chunks)} chunk(s) -> {args.provider}:{args.model}, {args.workers} worker(s)", file=sys.stderr)
    for c in chunks:
        print(f"[pipeline]   - {c.chunk_id} ({c.chunk_type}, {len(c.text)} chars)", file=sys.stderr)

    results: List[Dict[str, Any]] = []
    errors: List[tuple] = []

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        future_to_chunk = {pool.submit(process_chunk, provider, c): c for c in chunks}
        for fut in cf.as_completed(future_to_chunk):
            c = future_to_chunk[fut]
            try:
                results.append(fut.result())
                print(f"[pipeline] done:   {c.chunk_id}", file=sys.stderr)
            except Exception as e:  # noqa: BLE001 - surfaced to the user below
                errors.append((c.chunk_id, str(e)))
                print(f"[pipeline] FAILED: {c.chunk_id}: {e}", file=sys.stderr)

    merged = merge_results(results, source_file=str(args.input), provider_name=args.provider, model=args.model)
    if errors:
        merged["_pipeline_metadata"]["errors"] = [{"chunk_id": cid, "error": err} for cid, err in errors]

    Path(args.output).write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[pipeline] wrote {args.output}" + (f"  ({len(errors)} chunk(s) failed)" if errors else ""), file=sys.stderr)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Path to the raw input .txt file")
    ap.add_argument("--output", required=True, help="Path to write the resulting .json file")
    ap.add_argument("--provider", required=True, choices=["anthropic", "openai-compatible"], help="LLM backend to call")
    ap.add_argument("--model", required=True, help="Model name / deployment for the chosen provider")
    ap.add_argument("--api-key", default=None, help="Overrides the provider's default env var (ANTHROPIC_API_KEY / OPENAI_API_KEY)")
    ap.add_argument("--base-url", default=None, help="openai-compatible only: Azure / OpenRouter / local server base URL")
    ap.add_argument("--workers", type=int, default=4, help="Number of chunks to process in parallel (default: 4)")
    return ap


def main():
    args = build_arg_parser().parse_args()
    run(args)


if __name__ == "__main__":
    main()