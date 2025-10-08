#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import List


ORDER_GROUPS = [
    # structural anchors
    lambda c: c in {'frame','container','inner','content-width-container','card-surface'},
    lambda c: c.startswith('frame-'),
    # layout
    lambda c: c in {'layout-2col','layout-flex-row','layout-2col-equal','layout-image-text','layout-text-image'},
    # utilities (u-)
    lambda c: c.startswith('u-'),
    # typography bundles / tokens
    lambda c: c.startswith('tx-'),
    lambda c: c.startswith('t-'),
    lambda c: c.startswith('tw-') or c.startswith('lhpx-') or c.startswith('lhr-') or c.startswith('lhp-') or c.startswith('ta-') or c.startswith('ls-'),
    # visuals
    lambda c: c.startswith('vis-grad-') or c.startswith('visg-'),
    lambda c: c.startswith('vis-'),
    # remaining named classes
    lambda c: c in {'btn','btn--secondary','oswald'},
    # legacy fallbacks
    lambda c: c.startswith('u-sign-'),
    lambda c: c.startswith('v-'),
    lambda c: c.startswith('n-'),
]


def rank(cls: str) -> int:
    for i, pred in enumerate(ORDER_GROUPS):
        try:
            if pred(cls):
                return i
        except Exception:
            continue
    return len(ORDER_GROUPS)


def normalize_attr(classes: str) -> str:
    arr = [c for c in classes.split() if c]
    # drop duplicates, keep first occurrence
    seen = set()
    unique: List[str] = []
    for c in arr:
        if c == 'ls-0':
            continue
        if c in seen:
            continue
        seen.add(c)
        unique.append(c)
    # stable sort by group rank, keep inner order within same rank
    grouped: List[List[str]] = []
    for _ in range(len(ORDER_GROUPS)+1):
        grouped.append([])
    for c in unique:
        grouped[rank(c)].append(c)
    out: List[str] = []
    for g in grouped:
        out.extend(g)
    return ' '.join(out)


def main():
    ap = argparse.ArgumentParser(description='Normalize class attribute order and remove duplicates for readability')
    ap.add_argument('--root', required=True)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    if not html_path.exists():
        raise SystemExit('index.html not found')

    src = html_path.read_text(encoding='utf-8', errors='ignore')
    changed = 0

    def repl(m: re.Match) -> str:
        nonlocal changed
        before, classes, after = m.group(1), m.group(2), m.group(3)
        new = normalize_attr(classes)
        if new != classes:
            changed += 1
            return before + new + after
        return m.group(0)

    out = re.sub(r'(class=\")([^\"]+)(\")', repl, src)
    if args.dry_run:
        print(f"[NORM-ORDER] changed={changed}")
        return
    if changed:
        bak = root / 'index.html.normalize_order.bak'
        if not bak.exists():
            bak.write_text(src, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    print(f"[NORM-ORDER] changed={changed}")


if __name__ == '__main__':
    main()

