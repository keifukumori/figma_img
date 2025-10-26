#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_box_shadows(css_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text, flags=re.S):
        sels = m.group(1)
        body = m.group(2)
        if 'box-shadow' not in body:
            continue
        for s in sels.split(','):
            s = s.strip()
            if not s.startswith('.'):
                continue
            if s.startswith('.n-'):
                # Extract first box-shadow declaration
                bs = None
                for part in body.split(';'):
                    if ':' not in part:
                        continue
                    k, v = part.split(':', 1)
                    if k.strip().lower() == 'box-shadow':
                        bs = v.strip()
                        break
                if bs:
                    out[s[1:]] = bs
    return out


def promote(root: Path, backup: bool = False) -> tuple[int, int]:
    html = root / 'index.html'
    css = root / 'style.css'
    common = root / 'style-common.css'
    if not html.exists() or not css.exists():
        return (0, 0)
    css_text = css.read_text(encoding='utf-8', errors='ignore')
    bs_map = parse_box_shadows(css_text)
    src = html.read_text(encoding='utf-8', errors='ignore')

    # For each about__row-item (or section__row-item), look ahead limited lines for descendant n-* with box-shadow
    lines = src.splitlines()
    row_item_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\b[a-z0-9-]+__row-item\b[^\"]*)\"[^>]*>")
    class_re = re.compile(r'class=\"([^\"]+)\"')
    changed = False
    for i, line in enumerate(lines):
        m = row_item_re.match(line)
        if not m:
            continue
        indent = m.group(1)
        cls = m.group(2)
        # scan next ~20 lines for n-* with box-shadow
        bs_val = None
        j = i + 1
        end_re = re.compile(rf"^{re.escape(indent)}</div>\s*$")
        while j < len(lines) and j < i + 40 and not end_re.match(lines[j]):
            cm = class_re.search(lines[j])
            if cm:
                for tok in cm.group(1).split():
                    if tok.startswith('n-') and tok in bs_map:
                        bs_val = bs_map[tok]
                        break
            if bs_val:
                break
            j += 1
        if not bs_val:
            continue
        # ensure common css has rule
        existing = common.read_text(encoding='utf-8', errors='ignore') if common.exists() else ''
        section = None
        for t in cls.split():
            if '__row-item' in t:
                section = t.split('__', 1)[0]
                break
        sel = f":where(.{section}__row-item)" if section else ":where(.about__row-item)"
        rule = f"\n/* promote shadow to row-item */\n{sel}{{ box-shadow: {bs_val}; background-color:#fff; border-radius:8px; }}\n"
        if rule not in existing:
            common.write_text(existing + rule, encoding='utf-8')
            changed = True
    return (1 if changed else 0, 0)


def main():
    ap = argparse.ArgumentParser(description='Promote descendant n-* box-shadow to section__row-item (card-like)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()
    root = Path(args.root)
    files, _ = promote(root, backup=args.backup)
    print(f"[PROMOTE-SHADOW] style-common.css updated={files}")


if __name__ == '__main__':
    main()

