#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description='Append section-scoped card alias (section__card) to elements with class="card" within each <section class="SECTION ..."> block')
    ap.add_argument('--root', required=True, help='Root directory containing HTML files')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    files_changed = 0
    edits_total = 0

    # Simple line-based parser: track current section name, add alias to card-bearing tags until </section>
    open_section_re = re.compile(r"^(\s*)<section\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_section_re_tpl = r"^{indent}</section>\s*$"
    open_tag_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b([^>]*)>")
    class_re = re.compile(r"class=\"([^\"]+)\"")

    for html in root.rglob('*.html'):
        try:
            lines = html.read_text(encoding='utf-8', errors='ignore').splitlines()
        except Exception:
            continue
        changed = False
        i = 0
        while i < len(lines):
            msec = open_section_re.match(lines[i])
            if not msec:
                i += 1
                continue
            indent = msec.group(1)
            sec_classes = msec.group(2).split()
            section_name = sec_classes[0] if sec_classes else None
            close_re = re.compile(close_section_re_tpl.format(indent=re.escape(indent)))
            j = i + 1
            while j < len(lines) and not close_re.match(lines[j]):
                mtag = open_tag_re.match(lines[j])
                if mtag:
                    attrs = mtag.group(3)
                    cm = class_re.search(attrs)
                    if cm and 'card' in cm.group(1).split():
                        classes = cm.group(1).split()
                        # build alias
                        if section_name and not any(c.endswith('__card') for c in classes):
                            alias = f"{section_name}__card"
                            if alias not in classes:
                                classes.append(alias)
                                new_attrs = attrs[:cm.start()] + f'class="{' '.join(classes)}"' + attrs[cm.end():]
                                lines[j] = f"{mtag.group(1)}<{mtag.group(2)}{new_attrs}>"
                                changed = True
                                edits_total += 1
                j += 1
            i = j + 1
        if changed:
            if args.backup:
                html.with_suffix(html.suffix + '.sec_card.bak').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            html.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            files_changed += 1

    print(f"[SEC-CARD] files_changed={files_changed}, edits={edits_total}")


if __name__ == '__main__':
    main()

