#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def annotate_section_rows(root: Path, backup: bool = False) -> tuple[int, int]:
    files_changed = 0
    edits_total = 0

    # <section class="about ..."> ... </section> のスコープ内で、
    # eq-cols を持つ fx-row 親に about__row を付与する
    open_section_re = re.compile(r"^(\s*)<section\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_section_re_tpl = r"^{indent}</section>\s*$"
    open_row_re = re.compile(r"^(\s*)<div\b([^>]*)>\s*$", re.I)
    class_re = re.compile(r"class=\"([^\"]+)\"")
    # token regexes
    g_re = re.compile(r"\bg-(\d+)\b")
    ai_re = re.compile(r"\bai-([a-z-]+)\b")
    jc_re = re.compile(r"\bjc-([a-z-]+)\b")
    fw_re = re.compile(r"\bfw-(nowrap|wrap)\b")

    for hp in root.rglob('*.html'):
        try:
            lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
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
            section_name = None
            # Prefer explicitly assigned keys like section-01/02 or meaningful tokens
            for tok in sec_classes:
                if tok.startswith('section-'):
                    section_name = tok
                    break
            if section_name is None and sec_classes:
                # skip generic tokens
                generic = {'section','c-section','content-width-container'}
                for tok in sec_classes:
                    if tok not in generic:
                        section_name = tok
                        break
            if not section_name:
                i += 1
                continue
            close_section_re = re.compile(close_section_re_tpl.format(indent=re.escape(indent)))
            j = i + 1
            while j < len(lines) and not close_section_re.match(lines[j]):
                mrow = open_row_re.match(lines[j])
                if mrow:
                    attrs = mrow.group(2)
                    cm = class_re.search(attrs)
                    if cm:
                        cls_str = cm.group(1)
                        classes = cls_str.split()
                        has_fx = any(c == 'fx-row' for c in classes)
                        has_eq = any(c == 'eq-cols' for c in classes)
                        if has_fx and has_eq:
                            alias = f"{section_name}__row"
                            if alias not in classes:
                                classes.append(alias)
                                new_cls = ' '.join(classes)
                                new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
                                lines[j] = f"{mrow.group(1)}<div{new_attrs}>"
                                changed = True
                                edits_total += 1
                            # ensure minimal CSS for section row alias exists
                            try:
                                sc = (hp.parent / 'style-common.css')
                                css = sc.read_text(encoding='utf-8', errors='ignore') if sc.exists() else ''
                                # build declarations from tokens on the row
                                decls = []
                                mg = g_re.search(cls_str)
                                if mg:
                                    try:
                                        n = int(mg.group(1)); decls.append(f"gap:{n}px")
                                    except Exception:
                                        pass
                                mai = ai_re.search(cls_str)
                                if mai:
                                    # keep hyphen in values: flex-start, flex-end, center, stretch
                                    decls.append(f"align-items:{mai.group(1)}")
                                mjc = jc_re.search(cls_str)
                                if mjc:
                                    decls.append(f"justify-content:{mjc.group(1)}")
                                mfw = fw_re.search(cls_str)
                                if mfw:
                                    decls.append(f"flex-wrap:{mfw.group(1)}")
                                # children should not overflow under about__row
                                rule_child = f"\n/* section row base: children overflow guard */\n:where(.{alias}) > *{{min-width:0}}\n"
                                if rule_child not in css:
                                    css += rule_child
                                # section row baseline/rules from tokens (replace existing block for this alias)
                                if decls:
                                    # remove previous :where(.alias){...} blocks
                                    css = re.sub(rf"\:where\(\.{re.escape(alias)}\)\s*\{{[^\}}]*\}}", "", css)
                                    rule_row = f"\n/* section row extracted */\n:where(.{alias}){{{'; '.join(decls)} }}\n"
                                    css += rule_row
                                sc.write_text(css, encoding='utf-8')
                            except Exception:
                                pass
                            # Do NOT remove tokens here; keep HTML tokens until確認完了（安定優先）
                j += 1
            i = j + 1
        if changed:
            if backup:
                hp.with_suffix(hp.suffix + '.sec_row.bak').write_text('\n'.join(lines) + '\n', encoding='utf-8')
            hp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            files_changed += 1
    return files_changed, edits_total


def main():
    ap = argparse.ArgumentParser(description='Add section-scoped row alias (section__row) to fx-row parents with eq-cols inside each section')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    files, edits = annotate_section_rows(root, backup=args.backup)
    print(f"[SEC-ROW] files_changed={files}, edits={edits}")


if __name__ == '__main__':
    main()
