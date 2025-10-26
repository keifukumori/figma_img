#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


WHITELIST = {
    'display', 'flex-direction', 'gap', 'justify-content', 'align-items', 'flex-wrap', 'align-self'
}


def parse_css_rules(css_text: str) -> dict[str, dict[str, str]]:
    rules: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text):
        sel = m.group(1)
        if not sel.startswith('.n-'):
            continue
        body = m.group(2)
        kv: dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if not k:
                continue
            kv[k] = v
        if kv:
            rules[sel[1:]] = kv  # drop leading dot
    return rules


def main():
    ap = argparse.ArgumentParser(description="Remove n-* classes from HTML when their CSS only contains flex-layout props already covered by utilities")
    ap.add_argument('--root', required=True, help='Root directory containing style.css and index.html')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    if not css_path.exists():
        raise SystemExit('style.css not found under root')

    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    rules = parse_css_rules(css_text)
    removable: set[str] = set()
    for cls, kv in rules.items():
        # safe only if all props lie in WHITELIST
        if all(k in WHITELIST for k in kv.keys()):
            removable.add(cls)

    if not removable:
        print('[PRUNE-TRIVIAL-N] no trivial n-* classes detected')
        return

    class_attr_re = re.compile(r'(class=\")([^\"]+)(\")')
    files_changed = 0
    tokens_removed = 0
    for html in root.rglob('*.html'):
        src = html.read_text(encoding='utf-8', errors='ignore')
        changed_here = 0

        def repl(m: re.Match) -> str:
            nonlocal changed_here
            before, classes, after = m.group(1), m.group(2), m.group(3)
            toks = [c for c in classes.split() if c]
            kept = []
            for c in toks:
                if c.startswith('n-') and c in removable:
                    changed_here += 1
                    continue
                kept.append(c)
            if changed_here == 0:
                return m.group(0)
            return before + (" ".join(kept)) + after

        out = class_attr_re.sub(repl, src)
        if changed_here > 0 and not args.dry_run:
            if args.backup:
                bak = html.with_suffix(html.suffix + '.prune_trivial_n.bak')
                if not bak.exists():
                    bak.write_text(src, encoding='utf-8')
            html.write_text(out, encoding='utf-8')
            files_changed += 1
            tokens_removed += changed_here

    print(f'[PRUNE-TRIVIAL-N] files_changed={files_changed}, tokens_removed={tokens_removed}, candidates={len(removable)}')


if __name__ == '__main__':
    main()

