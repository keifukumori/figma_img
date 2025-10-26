#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description='Normalize stack alignment: for elements with about__stack, enforce ai-flex-start and drop conflicting ai-center/ai-stretch tokens')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')

    files_changed = 0
    edits = 0
    for html in root.rglob('*.html'):
        src = html.read_text(encoding='utf-8', errors='ignore')
        changed = False
        def repl(m: re.Match) -> str:
            nonlocal changed, edits
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                return m.group(0)
            classes = cm.group(1).split()
            if 'about__stack' not in classes:
                return m.group(0)
            # remove conflicting tokens
            filtered = [c for c in classes if c not in ('ai-center', 'ai-stretch')]
            if 'ai-flex-start' not in filtered:
                filtered.append('ai-flex-start')
            if filtered == classes:
                return m.group(0)
            changed = True
            edits += 1
            new_attrs = attrs[:cm.start()] + f'class="{' '.join(filtered)}"' + attrs[cm.end():]
            return f"<{m.group(1)}{new_attrs}>"

        out = tag_re.sub(repl, src)
        if changed:
            if args.backup:
                html.with_suffix(html.suffix + '.stack_align.bak').write_text(src, encoding='utf-8')
            html.write_text(out, encoding='utf-8')
            files_changed += 1
    print(f"[STACK-NORM] files_changed={files_changed}, edits={edits}")


if __name__ == '__main__':
    main()

