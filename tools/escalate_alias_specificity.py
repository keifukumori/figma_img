#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


ALIAS_RE = re.compile(r":where\(\.(?P<cls>[a-zA-Z0-9_-]+)\)\s*\{(?P<body>[^}]*)\}")


def escalate_in_css(css_path: Path, backup: bool = False) -> int:
    if not css_path.exists():
        return 0
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    orig = css
    # Build new rules for each :where(.cls){...}
    additions: list[str] = []
    seen_aliases: set[str] = set()

    # Skip if a plain .cls rule already exists with same body (approximate by selector presence)
    for m in ALIAS_RE.finditer(css):
        cls = m.group('cls').strip()
        body = m.group('body').strip()
        if not cls:
            continue
        if cls in seen_aliases:
            continue
        # If a plain .cls rule exists anywhere, skip adding to avoid duplication growth
        if re.search(rf"\.{re.escape(cls)}\s*\{{", css):
            continue
        rule = f"\n/* escalated */\n.{cls}{{{body}}}\n"
        additions.append(rule)
        seen_aliases.add(cls)

    if additions:
        if backup:
            bak = css_path.with_suffix(css_path.suffix + '.escalated.bak')
            if not bak.exists():
                bak.write_text(orig, encoding='utf-8')
        css += ''.join(additions)
        css_path.write_text(css, encoding='utf-8')
        return len(additions)
    return 0


def main():
    ap = argparse.ArgumentParser(description='Duplicate :where(.alias){...} rules as .alias{...} to raise specificity')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    # Prefer style-common.css first; also scan style.css
    total = 0
    for name in ('style-common.css', 'style.css'):
        total += escalate_in_css(root / name, backup=args.backup)
    print(f"[ESCALATE-ALIAS] rules_added={total}")


if __name__ == '__main__':
    main()

