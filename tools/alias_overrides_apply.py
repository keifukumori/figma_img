#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict


def load_map(path: Path) -> Dict[str, str]:
    data = json.loads(path.read_text(encoding='utf-8'))
    if isinstance(data, dict):
        return {str(k): str(v) for k, v in data.items()}
    if isinstance(data, list):
        out: Dict[str, str] = {}
        for item in data:
            if isinstance(item, dict) and 'from' in item and 'to' in item:
                out[str(item['from'])] = str(item['to'])
        return out
    return {}


def apply_html(html_path: Path, mapping: Dict[str, str], backup: bool) -> int:
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    orig = text
    # class="..." 内のトークンを置換（完全一致）
    def repl(m: re.Match) -> str:
        classes = m.group(1)
        toks = classes.split()
        changed = False
        for i, t in enumerate(toks):
            new = mapping.get(t)
            if new and new != t:
                toks[i] = new
                changed = True
        return f'class="{" ".join(toks)}"' if changed else m.group(0)

    text2 = re.sub(r'class=\"([^\"]+)\"', repl, text)
    if text2 != orig:
        if backup:
            html_path.with_suffix(html_path.suffix + '.aliasov.bak').write_text(orig, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')
        return 1
    return 0


def apply_css(css_path: Path, mapping: Dict[str, str], backup: bool) -> int:
    if not css_path.exists():
        return 0
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    orig = css
    # .from → .to, :where(.from) → .to （セレクタ中の完全一致）
    for src, dst in mapping.items():
        if not src or not dst or src == dst:
            continue
        css = re.sub(rf":where\(\.{re.escape(src)}\)", f".{dst}", css)
        css = re.sub(rf"(?<![a-zA-Z0-9_-])\.{re.escape(src)}(?![a-zA-Z0-9_-])", f".{dst}", css)
    if css != orig:
        if backup:
            css_path.with_suffix(css_path.suffix + '.aliasov.bak').write_text(orig, encoding='utf-8')
        css_path.write_text(css, encoding='utf-8')
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description='Apply alias overrides to HTML and CSS (normalize BEM/alias names)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--map', dest='mapfile', required=True, help='JSON mapping file ({"from":"to",...} or [{"from":..,"to":..}])')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    mapping = load_map(Path(args.mapfile))
    if not mapping:
        print('[ALIAS-OV] empty mapping; nothing to apply')
        return
    changed = 0
    # HTML
    for hp in root.rglob('*.html'):
        try:
            changed += apply_html(hp, mapping, backup=args.backup)
        except Exception:
            continue
    # CSS
    for name in ('style.css', 'style-pc.css', 'style-sp.css', 'style-common.css'):
        try:
            changed += apply_css(root / name, mapping, backup=args.backup)
        except Exception:
            continue
    print(f"[ALIAS-OV] changes={changed}")


if __name__ == '__main__':
    main()

