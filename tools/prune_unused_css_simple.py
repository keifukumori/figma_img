#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import List, Tuple


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def find_at_block_ranges(css: str) -> List[Tuple[int, int]]:
    """Return list of [start,end) ranges of top-level @-blocks, after comments removed."""
    ranges = []
    n = len(css)
    i = 0
    while i < n:
        ch = css[i]
        if ch == '@':
            # find next '{'
            j = css.find('{', i)
            if j == -1:
                break
            # scan to matching '}'
            depth = 1
            k = j + 1
            while k < n and depth:
                if css[k] == '{':
                    depth += 1
                elif css[k] == '}':
                    depth -= 1
                k += 1
            end = k
            ranges.append((i, end))
            i = end
        else:
            i += 1
    return ranges


def in_any_range(pos: int, ranges: List[Tuple[int, int]]) -> bool:
    for a, b in ranges:
        if a <= pos < b:
            return True
    return False


def prune_simple_class_rules(css: str, unused: set[str]) -> Tuple[str, int]:
    base = strip_comments(css)
    at_ranges = find_at_block_ranges(base)
    out_parts: List[str] = []
    i = 0
    removed = 0
    n = len(css)
    # Use regex to find simple class starts; operate on original css (keeping formatting), but check ranges on comment-stripped copy
    for m in re.finditer(r"(^|\n)(\s*)\.([a-zA-Z0-9_-]+)\s*\{", css):
        start = m.start(0)
        brace_pos = m.end(0) - 1  # position of '{'
        cls = m.group(3)
        # skip if class not in unused
        if cls not in unused:
            continue
        # check not within @-block by mapping index into comment-stripped text isn't trivial.
        # Approximation: re-run on stripped text to find a corresponding match window by selector string near position.
        # Instead, conservatively skip if previous 200 chars contain '@' without closing '{' -- fallback to simple check.
        prev = css[max(0, start - 200):start]
        if '@' in prev and '{' not in prev.split('@')[-1]:
            # likely within @-prelude; skip
            continue
        # find end of this rule by balancing braces from brace_pos
        depth = 1
        k = brace_pos + 1
        while k < n and depth:
            if css[k] == '{':
                depth += 1
            elif css[k] == '}':
                depth -= 1
            k += 1
        end = k
        # Only treat as simple selector if the selector line doesn't include ',' or other selectors
        selector_segment = css[m.start(2):brace_pos]
        if ',' in selector_segment:
            continue
        # write chunk before
        out_parts.append(css[i:start])
        # drop this block
        removed += 1
        i = end
    out_parts.append(css[i:])
    return (''.join(out_parts), removed)


def main():
    ap = argparse.ArgumentParser(description='Prune unused simple class selectors from style.css based on unused_css_report.json')
    ap.add_argument('--root', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    report_path = root / 'unused_css_report.json'
    if not css_path.exists() or not report_path.exists():
        raise SystemExit('Missing style.css or unused_css_report.json')

    report = json.loads(report_path.read_text(encoding='utf-8'))
    unused_list = report.get('unused_classes') or []
    unused = set(unused_list)

    css = css_path.read_text(encoding='utf-8', errors='ignore')
    new_css, removed = prune_simple_class_rules(css, unused)

    if args.dry_run:
        print(f"[PRUNE-CSS] would remove {removed} simple class rules")
        return

    if removed:
        bak = root / 'style.css.prune.bak'
        if not bak.exists():
            bak.write_text(css, encoding='utf-8')
        css_path.write_text(new_css, encoding='utf-8')
    print(f"[PRUNE-CSS] removed {removed} simple class rules; backup: style.css.prune.bak")


if __name__ == '__main__':
    main()

