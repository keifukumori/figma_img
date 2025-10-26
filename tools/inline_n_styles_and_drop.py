#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_n_rules(css_text: str) -> dict[str, str]:
    """Return map: n-token -> declarations (string). Handles single or multi-selector rules that include .n-.."""
    nmap: dict[str, str] = {}
    # Match blocks like ".n-abc, .alias { ... }" or ".alias, .n-abc { ... }"
    for m in re.finditer(r"([^{]+)\{([^}]*)\}", css_text, flags=re.S):
        selectors = m.group(1)
        body = m.group(2)
        # normalize whitespace inside body (keep as-is otherwise)
        decls = "; ".join([p.strip() for p in body.split(';') if ':' in p])
        for nm in re.finditer(r"\.n-([a-zA-Z0-9_-]+)", selectors):
            tok = 'n-' + nm.group(1)
            nmap[tok] = decls
    return nmap


def main():
    ap = argparse.ArgumentParser(description='Inline CSS of .n-* rules into HTML and drop the .n-* class tokens')
    ap.add_argument('--root', required=True, help='Root directory containing HTML and style.css')
    ap.add_argument('--backup', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    if not css_path.exists():
        raise SystemExit('style.css not found under root')
    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    nmap = parse_n_rules(css_text)
    if not nmap:
        print('[INLINE-N] no .n-* rules detected; nothing to do')
        return

    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')
    style_attr_re = re.compile(r'style=\"([^\"]*)\"')

    files_changed = 0
    attrs_changed = 0

    for html in root.rglob('*.html'):
        try:
            src = html.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue

        edits = []

        for m in tag_re.finditer(src):
            full = m.group(0)
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1)
            toks = [c for c in classes.split() if c]
            n_tokens = [c for c in toks if c.startswith('n-') and c in nmap]
            if not n_tokens:
                continue
            # Collect decls
            decls = []
            for t in n_tokens:
                body = nmap.get(t)
                if body:
                    decls.append(body)
            if not decls:
                continue
            # Remove n- tokens
            kept = [c for c in toks if c not in n_tokens]
            new_classes = ' '.join(kept)
            # Merge style
            sm = style_attr_re.search(attrs)
            if sm:
                existing = sm.group(1)
                merged = (existing.rstrip(';') + '; ' + '; '.join(decls)).strip('; ') if existing else '; '.join(decls)
                new_attrs = attrs[:sm.start()] + f'style="{merged}"' + attrs[sm.end():]
            else:
                new_attrs = attrs + f' style="{"; ".join(decls)}"'
            # Replace class attr inside attrs
            new_attrs = new_attrs[:cm.start()] + f'class="{new_classes}"' + new_attrs[cm.end():]
            new_tag = f'<{m.group(1)}{new_attrs}>'
            edits.append((m.start(), m.end(), new_tag))
            attrs_changed += 1

        if edits:
            edits.sort(reverse=True)
            out = src
            for s, e, rep in edits:
                out = out[s:e].replace(out[s:e], rep, 1) if False else out[:s] + rep + out[e:]
            if not args.dry_run:
                if args.backup:
                    bak = html.with_suffix(html.suffix + '.inline_n.bak')
                    if not bak.exists():
                        Path(str(bak)).write_text(src, encoding='utf-8')
                html.write_text(out, encoding='utf-8')
                files_changed += 1

    print(f'[INLINE-N] files_changed={files_changed}, class_attrs_modified={attrs_changed}')


if __name__ == '__main__':
    main()
