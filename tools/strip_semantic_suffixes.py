#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description='Strip numeric-tailed semantic tokens (e.g., about__d-flex_284) and ensure canonical is present')
    ap.add_argument('--root', required=True, help='Project root containing index.html')
    ap.add_argument('--prefix', required=True, help='Token prefix to strip (e.g., about__d-flex_)')
    ap.add_argument('--canonical', required=True, help='Canonical token to ensure (e.g., about__d-flex)')
    ap.add_argument('--require-class', action='append', help='Only strip when all these classes are present on the element (can be repeated)')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    if not html_path.exists():
        raise SystemExit('index.html not found')

    src = html_path.read_text(encoding='utf-8', errors='ignore')
    changed = 0
    # match class attributes
    cre = re.compile(r'(class=\")([^\"]+)(\")')
    # token to strip: prefix + digits (and optional more digits/letters)
    strip_re = re.compile(rf'\b{re.escape(args.prefix)}\d+\b')

    def repl(m: re.Match) -> str:
        nonlocal changed
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = [c for c in classes.split() if c]
        orig = list(arr)
        # require-class check
        if args.require_class:
            have = set(arr)
            for rc in args.require_class:
                if rc not in have:
                    return m.group(0)
        # remove prefixed tokens
        arr = [c for c in arr if not strip_re.fullmatch(c)]
        s = set(arr)
        if args.canonical not in s:
            arr.append(args.canonical)
        if arr != orig:
            changed += 1
            return before + ' '.join(arr) + after
        return m.group(0)

    out = cre.sub(repl, src)
    if args.dry_run:
        print(f"[STRIP-SEM] would change {changed} class attributes")
        return
    if changed:
        bak = html_path.with_suffix(html_path.suffix + '.strip_semantics.bak')
        if not bak.exists():
            bak.write_text(src, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    print(f"[STRIP-SEM] changed {changed} class attributes")


if __name__ == '__main__':
    main()
