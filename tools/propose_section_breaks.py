#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


SECTION_OPEN_RE = re.compile(r"^(\s*)<section\b[^>]*\bclass=\"([^\"]+)\"[^>]*>", re.I)
SECTION_CLOSE_TPL = r"^{indent}</section>\s*$"
TAG_OPEN_RE = re.compile(r"^(\s*)<([a-zA-Z][a-zA-Z0-9-]*)\b([^>]*)>")
CLASS_RE = re.compile(r"class=\"([^\"]+)\"")


def find_break_reasons(tag: str, attrs: str, classes: List[str], line_text: str) -> List[str]:
    reasons: List[str] = []
    # Headings / semantic large text
    if tag.lower() in {"h1","h2","h3"}:
        reasons.append("heading")
    if any((c.startswith('figma-style-hedding') or c.startswith('text-size-')) for c in classes):
        reasons.append("typography")
    # Background / fullbleed
    if 'bg-fullbleed' in classes or re.search(r"background\s*:\s*url\(|background-image\s*:\s*url\(", attrs, re.I):
        reasons.append("background")
    # Rule lines / separators
    if 'line' in classes:
        reasons.append("rule")
    # Layout mode change indicators
    if any(c in classes for c in ("fx-row","fx-col","eq-cols","layout-3col","layout-2col")):
        reasons.append("layout")
    # Large spacing tokens
    for c in classes:
        m = re.match(r"g-(\d+)$", c)
        if m:
            try:
                n = int(m.group(1))
                if n >= 40:
                    reasons.append("large-gap")
            except Exception:
                pass
    return list(dict.fromkeys(reasons))  # dedupe, keep order


def propose_breaks_in_file(html_path: Path) -> Dict:
    lines = html_path.read_text(encoding='utf-8', errors='ignore').splitlines()
    proposals: List[Dict] = []
    i = 0
    while i < len(lines):
        msec = SECTION_OPEN_RE.match(lines[i])
        if not msec:
            i += 1
            continue
        indent = msec.group(1)
        sec_classes = msec.group(2).split()
        sec_name = sec_classes[0] if sec_classes else 'section'
        close_re = re.compile(SECTION_CLOSE_TPL.format(indent=re.escape(indent)))
        j = i + 1
        candidates: List[Dict] = []
        last_reason_line = -999
        while j < len(lines) and not close_re.match(lines[j]):
            mtag = TAG_OPEN_RE.match(lines[j])
            if mtag:
                tag = mtag.group(2)
                attrs = mtag.group(3)
                cm = CLASS_RE.search(attrs)
                classes = cm.group(1).split() if cm else []
                reasons = find_break_reasons(tag, attrs, classes, lines[j])
                if reasons:
                    # throttle: avoid consecutive lines producing many entries; merge window = 2 lines
                    if j - last_reason_line > 2:
                        snippet = lines[j].strip()
                        candidates.append({
                            'line': j + 1,
                            'reasons': reasons,
                            'context': snippet[:240],
                        })
                        last_reason_line = j
            j += 1
        proposals.append({
            'section': sec_name,
            'file': str(html_path.name),
            'candidates': candidates,
        })
        i = j + 1
    return {
        'file': str(html_path),
        'proposals': proposals,
    }


def main():
    ap = argparse.ArgumentParser(description='Propose intra-section breakpoints (report only) based on headings/background/layout/spacing heuristics')
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', help='Output JSON file (default: section_breaks.json in root)')
    args = ap.parse_args()

    root = Path(args.root)
    out_path = Path(args.out) if args.out else (root / 'section_breaks.json')
    report: Dict[str, List[Dict]] = {}
    for hp in sorted(root.rglob('*.html')):
        try:
            rep = propose_breaks_in_file(hp)
        except Exception:
            continue
        if rep and rep.get('proposals'):
            report[str(hp.relative_to(root))] = rep['proposals']
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[SECTION-BREAKS] written={out_path} files={len(report)}")


if __name__ == '__main__':
    main()

