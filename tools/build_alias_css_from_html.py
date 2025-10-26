#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List


WHITELIST = {"background-color", "border-radius", "overflow",
             "padding", "padding-top", "padding-right", "padding-bottom", "padding-left"}


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
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if not k:
                continue
            decls[k] = v
        if not decls:
            continue
        for cls in re.findall(r"\.([a-zA-Z0-9_-]+)", sels):
            d = cmap.setdefault(cls, {})
            d.update(decls)
    return cmap


def write_or_merge_rule(css_path: Path, cls: str, props: Dict[str, str]) -> None:
    """Append or merge a rule for .cls with given props (only adds missing or differing props at end)."""
    css = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ""
    # Simple: append a new rule for alias; idempotent by skipping if identical lines already exist
    body = "; ".join(f"{k}: {v}" for k, v in sorted(props.items()))
    rule = f"\n/* alias cluster */\n.{cls} {{ {body}; }}\n"
    if body and rule not in css:
        with css_path.open('a', encoding='utf-8') as f:
            f.write(rule)


def main():
    ap = argparse.ArgumentParser(description='Build alias CSS from HTML clusters: compute intersection of n-* visual props and emit .alias rules')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    if not css_path.exists():
        raise SystemExit('style.css not found')
    css_map = parse_css_classes(css_path.read_text(encoding='utf-8', errors='ignore'))

    # Find alias classes in HTML (section__*) and collect their n-* members
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*?)>", re.I)
    class_re = re.compile(r"class=\"([^\"]+)\"")
    alias_to_n: Dict[str, List[str]] = {}
    for hp in root.rglob('*.html'):
        text = hp.read_text(encoding='utf-8', errors='ignore')
        for m in tag_re.finditer(text):
            cm = class_re.search(m.group(2))
            if not cm:
                continue
            classes = cm.group(1).split()
            n_tokens = [c for c in classes if c.startswith('n-')]
            aliases = [c for c in classes if '__' in c]
            if not aliases or not n_tokens:
                continue
            for al in aliases:
                lst = alias_to_n.setdefault(al, [])
                for n in n_tokens:
                    if n not in lst:
                        lst.append(n)

    # For each alias, compute intersection of WHITELIST props across its n-* classes
    total_written = 0
    if args.backup:
        bak = css_path.with_suffix(css_path.suffix + '.alias.bak')
        if not bak.exists():
            bak.write_text(css_path.read_text(encoding='utf-8', errors='ignore'), encoding='utf-8')
    for al, ns in alias_to_n.items():
        if len(ns) < 2:
            continue
        # start with props of first n
        base = {k: v for k, v in (css_map.get(ns[0], {}) or {}).items() if k in WHITELIST}
        for n in ns[1:]:
            kv = {k: v for k, v in (css_map.get(n, {}) or {}).items() if k in WHITELIST}
            # intersect by equal values
            base = {k: v for k, v in base.items() if k in kv and kv[k] == v}
            if not base:
                break
        if base:
            write_or_merge_rule(css_path, al, base)
            total_written += 1
    print(f"[ALIAS-CSS] aliases={len(alias_to_n)}, written={total_written}")


if __name__ == '__main__':
    main()
