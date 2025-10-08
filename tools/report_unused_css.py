#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def collect_used_classes_from_html(html_text: str) -> set[str]:
    used = set()
    for m in re.finditer(r'class=\"([^\"]+)\"', html_text):
        for c in m.group(1).split():
            if c:
                used.add(c)
    return used


def parse_simple_class_rules(css_text: str) -> dict[str, int]:
    # Return map class -> count of simple top-level rules
    simple = {}
    for m in re.finditer(r"(^|\n)\s*\.(?P<c>[a-zA-Z0-9_-]+)\s*\{", css_text):
        c = m.group('c')
        simple[c] = simple.get(c, 0) + 1
    return simple


def main():
    ap = argparse.ArgumentParser(description='Report unused simple CSS class selectors against index.html')
    ap.add_argument('--root', required=True)
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    css_path = root / 'style.css'
    if not html_path.exists() or not css_path.exists():
        raise SystemExit('Missing index.html or style.css')

    html_text = html_path.read_text(encoding='utf-8', errors='ignore')
    css_text = css_path.read_text(encoding='utf-8', errors='ignore')

    used = collect_used_classes_from_html(html_text)
    simple = parse_simple_class_rules(css_text)

    # Exclude globals and generated families we intentionally keep
    ignore_prefixes = ('device-',)
    ignore_exact = {'container','inner','content-width-container','full-width-container'}

    unused = []
    for cls in simple.keys():
        if cls in used:
            continue
        if cls in ignore_exact:
            continue
        if any(cls.startswith(p) for p in ignore_prefixes):
            continue
        unused.append(cls)

    report = {
        'total_simple_rules': len(simple),
        'used_classes_in_html': len([c for c in simple if c in used]),
        'unused_classes': sorted(unused)[:1000],
        'unused_count': len(unused),
    }
    out = root / 'unused_css_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[UNUSED-CSS] Report: {out} (unused={report['unused_count']}/{report['total_simple_rules']})")


if __name__ == '__main__':
    main()

