#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


STEPS = [
    ["python3", "tools/pipeline/postprocess_dedupe.py", "--root", "{root}", "--inject-css", "--backup"],
    ["python3", "tools/span_from_json.py", "--root", "{root}", "--backup"],
    ["python3", "tools/detect_spans.py", "--root", "{root}", "--backup"],
    ["python3", "tools/global_consolidate_components.py", "--root", "{root}", "--backup"],
    ["python3", "tools/pipeline/annotate_generic_components.py", "--root", "{root}"],
    ["python3", "tools/ops/add_section_card_alias.py", "--root", "{root}"],
    ["python3", "tools/discover_components.py", "--root", "{root}", "--apply"],
    ["python3", "tools/canonicalize_bem_variants.py", "--root", "{root}", "--backup"],
    ["python3", "tools/generate_macros.py", "--root", "{root}", "--macros", "tools/macros.json", "--collapse", "--backup"],
    ["python3", "tools/build_alias_css_from_html.py", "--root", "{root}", "--backup"],
    ["python3", "tools/normalize_stack_alignment.py", "--root", "{root}", "--backup"],
    ["python3", "tools/ops/drop_n_if_covered.py", "--root", "{root}", "--backup"],
    ["python3", "tools/report_residuals.py", "--root", "{root}", "--visuals"],
]


def run(cmd):
    print("[PIPE]", " ".join(cmd))
    subprocess.run(cmd, check=False)


def main():
    ap = argparse.ArgumentParser(description="Apply readability/maintainability optimizations to a generated project root")
    ap.add_argument("--root", required=True, help="Root project directory (contains index.html/style.css)")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        raise SystemExit(f"root not found: {root}")
    for step in STEPS:
        cmd = [p.format(root=str(root)) for p in step]
        run(cmd)
    print("[PIPE] done")


if __name__ == "__main__":
    main()
