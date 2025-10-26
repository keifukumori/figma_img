#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, List


def load_macros(path: Path) -> List[dict]:
    data = json.loads(path.read_text(encoding='utf-8'))
    return data.get('macros', [])


def tokens_to_css(tokens: List[str]) -> List[str]:
    css: List[str] = []
    for t in tokens:
        if t == 'fx-row':
            css.append('display:flex'); css.append('flex-direction:row')
        elif t == 'fx-col':
            css.append('display:flex'); css.append('flex-direction:column')
        elif t.startswith('g-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'gap:{n}px')
            except Exception:
                pass
        elif t.startswith('ai-'):
            css.append(f'align-items:{t[3:]}')
        elif t.startswith('jc-'):
            css.append(f'justify-content:{t[3:]}')
        elif t.startswith('fw-'):
            css.append(f'flex-wrap:{t[3:]}')
        elif t == 'w-full':
            css.append('width:100%')
        elif t == 'w-auto':
            css.append('width:auto')
        elif t == 'h-full':
            css.append('height:100%')
        elif t == 'h-auto':
            css.append('height:auto')
        elif t.startswith('px-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-left:{n}px'); css.append(f'padding-right:{n}px')
            except Exception:
                pass
        elif t.startswith('py-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-top:{n}px'); css.append(f'padding-bottom:{n}px')
            except Exception:
                pass
        elif t.startswith('pt-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-top:{n}px')
            except Exception:
                pass
        elif t.startswith('pr-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-right:{n}px')
            except Exception:
                pass
        elif t.startswith('pb-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-bottom:{n}px')
            except Exception:
                pass
        elif t.startswith('pl-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'padding-left:{n}px')
            except Exception:
                pass
        elif t.startswith('as-'):
            css.append(f'align-self:{t[3:]}')
        elif t == 'clip':
            css.append('overflow:hidden')
        elif t == 'flex-1':
            css.append('flex:1 1 0')
        elif t.startswith('basis-'):
            try:
                n = int(t.split('-',1)[1]); css.append(f'flex:0 0 {n}px'); css.append(f'width:{n}px')
            except Exception:
                pass
        # ignore others
    # de-dup by prop name, keep last
    prop_map: Dict[str, str] = {}
    for decl in css:
        if ':' in decl:
            k = decl.split(':',1)[0].strip().lower()
            prop_map[k] = decl
    return list(prop_map.values())


def emit_macro_css(style_common: Path, name: str, tokens: List[str]):
    decls = tokens_to_css(tokens)
    if not decls:
        return
    css = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
    rule = f"\n/* macro: {name} */\n:where(.{name}){{{'; '.join(decls)} }}\n"
    if rule not in css:
        with style_common.open('a', encoding='utf-8') as f:
            f.write(rule)


def apply_macros_to_html(root: Path, macros: List[dict], collapse: bool, backup: bool):
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')
    files_changed = 0
    edits = 0
    for hp in root.rglob('*.html'):
        src = hp.read_text(encoding='utf-8', errors='ignore')
        def repl(m: re.Match) -> str:
            nonlocal edits
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                return m.group(0)
            classes = cm.group(1).split()
            changed_local = False
            for macro in macros:
                name = macro.get('name'); toks = macro.get('tokens') or []
                if not name or not toks:
                    continue
                if all(t in classes for t in toks):
                    if name not in classes:
                        classes.append(name); changed_local = True
                    if collapse or macro.get('collapse'):
                        # remove tokens covered by macro
                        classes = [c for c in classes if c not in toks or c == name]
                        changed_local = True
            if not changed_local:
                return m.group(0)
            edits += 1
            new_attrs = attrs[:cm.start()] + f'class="{' '.join(classes)}"' + attrs[cm.end():]
            return f"<{m.group(1)}{new_attrs}>"
        out = tag_re.sub(repl, src)
        if out != src:
            if backup:
                hp.with_suffix(hp.suffix + '.macros.bak').write_text(src, encoding='utf-8')
            hp.write_text(out, encoding='utf-8')
            files_changed += 1
    print(f"[MACROS] files_changed={files_changed}, edits={edits}")


def main():
    ap = argparse.ArgumentParser(description='Generate composite macros and apply to HTML')
    ap.add_argument('--root', required=True, help='Project root containing index.html/style.css')
    ap.add_argument('--macros', default='tools/macros.json', help='Path to macros.json')
    ap.add_argument('--collapse', action='store_true', help='Remove covered utility tokens when macro is applied')
    ap.add_argument('--no-css', action='store_true', help='Do not emit macro CSS into style-common.css')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    macros = load_macros(Path(args.macros))
    style_common = root / 'style-common.css'
    if not args.no_css:
        for mdef in macros:
            if mdef.get('emit_css'):
                emit_macro_css(style_common, mdef['name'], mdef.get('tokens') or [])
    apply_macros_to_html(root, macros, args.collapse, args.backup)


if __name__ == '__main__':
    main()
