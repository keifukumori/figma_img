#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict


def parse_css_classes(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css_text):
        sels = m.group(1)
        body = m.group(2)
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip())
            decls[k] = v
        if not decls:
            continue
        for cls in re.findall(r"\.([a-zA-Z0-9_-]+)", sels):
            d = cmap.setdefault(cls, {})
            d.update(decls)
    return cmap


def is_card_like(decls: Dict[str, str]) -> bool:
    # Heuristics: white-ish background AND (radius or shadow) OR overflow hidden with radius
    bg = decls.get('background-color') or decls.get('background')
    radius = decls.get('border-radius')
    shadow = decls.get('box-shadow')
    overflow = decls.get('overflow')
    if overflow and 'hidden' in overflow and radius:
        return True
    if bg and (radius or shadow):
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description='Annotate generic components (card) and section-scoped card aliases based on CSS heuristics')
    ap.add_argument('--root', required=True, help='Project root containing index.html and style.css')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    css_path = root / 'style.css'
    if not html_path.exists() or not css_path.exists():
        raise SystemExit('Missing index.html or style.css')

    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    cmap = parse_css_classes(css_text)

    src = html_path.read_text(encoding='utf-8', errors='ignore')
    changed = 0

    # class attr regex
    cre = re.compile(r'(class=\")([^\"]+)(\")')

    def repl(m: re.Match) -> str:
        nonlocal changed
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        arr_set = set(arr)
        # skip if already annotated
        if 'card' in arr_set:
            return m.group(0)
        # Determine if any class is card-like by CSS
        cardish = False
        for c in arr:
            decls = cmap.get(c)
            if decls and is_card_like(decls):
                cardish = True
                break
        if not cardish:
            return m.group(0)
        # add generic card
        arr.append('card')
        # add section-scoped alias if present, e.g., about__d-flex(_NNN) -> about__card
        canon = None
        for c in arr:
            mm = re.match(r'([a-z0-9-]+)__([a-z0-9-]+)(?:_\d+)?$', c)
            if mm:
                section = mm.group(1)
                canon = f"{section}__card"
                break
        if canon and canon not in arr_set:
            arr.append(canon)
        changed += 1
        return before + ' '.join(arr) + after

    out = cre.sub(repl, src)
    if args.dry_run:
        print(f"[GEN-COMP] would annotate {changed} elements as card/section__card")
        return
    if changed:
        bak = html_path.with_suffix(html_path.suffix + '.gen_components.bak')
        if not bak.exists():
            bak.write_text(src, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    # ensure minimal .card rule exists (look for a real top-level .card selector)
    if not re.search(r"(^|[\n\r\s])\.card\s*\{", css_text):
        with css_path.open('a', encoding='utf-8') as f:
            f.write('\n\n/* === Generic card utility (minimal) === */\n.card{background-color:#fff;border-radius:8px;box-shadow:0 0 20px rgba(0,0,0,0.10);overflow:hidden}\n')
    print(f"[GEN-COMP] annotated {changed} elements")


if __name__ == '__main__':
    main()
