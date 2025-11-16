#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, Tuple


def parse_css_map(css_text: str) -> dict[str, dict[str, str]]:
    m: dict[str, dict[str, str]] = {}
    # Strip comments to simplify selector parsing
    css_text = re.sub(r"/\*.*?\*/", "", css_text or "", flags=re.S)
    for sel, body in re.findall(r"([^{}]+)\{([^}]*)\}", css_text or ""):
        decls: dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip())
            if k:
                decls[k] = v
        if not decls:
            continue
        # Collect any class tokens in selector (simple and :where cases)
        for c in re.findall(r"\.([a-zA-Z0-9_-]+)", sel):
            m.setdefault(c, {}).update(decls)
        for c in re.findall(r":where\(\.([a-zA-Z0-9_-]+)\)\s*", sel):
            m.setdefault(c, {}).update(decls)
    return m


def rgba_to_hex(color: str) -> Tuple[str, str]:
    c = color.strip().lower()
    # already hex
    if re.match(r"^#([0-9a-f]{3}|[0-9a-f]{6})$", c):
        hexv = c[1:] if len(c) == 7 else ''.join([ch*2 for ch in c[1:]])
        return hexv, color
    # named colors
    if c in ("white", "black"):
        return ("ffffff" if c == "white" else "000000"), color
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([0-9.]+)\s*)?\)", c)
    if not m:
        # fallback: sanitize to util-safe
        safe = re.sub(r"[^a-z0-9]+", "-", c)
        return safe[:12], color
    r, g, b = [max(0, min(255, int(m.group(i)))) for i in (1, 2, 3)]
    hexv = f"{r:02x}{g:02x}{b:02x}"
    # keep original formatting for CSS value
    return hexv, color


def util_name_for_color(color: str) -> Tuple[str, str]:
    hexv, css_val = rgba_to_hex(color)
    if hexv == 'ffffff':
        return 'tc-white', css_val
    if hexv == '000000':
        return 'tc-black', css_val
    return f'tc-{hexv}', css_val


def ensure_util(css_common: Path, util: str, color_value: str) -> bool:
    css = css_common.read_text(encoding='utf-8', errors='ignore') if css_common.exists() else ''
    if re.search(rf":where\(\.{re.escape(util)}\)\s*\{{[^}}]*color\s*:\s*", css):
        return False
    rule = f":where(.{util}){{ color: {color_value}; }}\n"
    if not css_common.exists():
        css_common.parent.mkdir(parents=True, exist_ok=True)
        css_common.write_text('/* Auto-generated common text color utilities */\n' + rule, encoding='utf-8')
        return True
    css_common.write_text(css + ("\n\n" if not css.endswith('\n') else '') + rule, encoding='utf-8')
    return True


def annotate_html(root: Path, class_to_util: dict[str, str]) -> int:
    changed_files = 0
    tag_re = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')
    for hp in root.rglob('*.html'):
        text = hp.read_text(encoding='utf-8', errors='ignore')
        out = text
        edits = []
        for m in tag_re.finditer(text):
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1).split()
            target_utils = set()
            # prefer n-* color util if present; else fallback to role color util
            util_found = None
            for c in classes:
                if c.startswith('n-') and c in class_to_util:
                    util_found = class_to_util[c]
                    break
            if not util_found:
                for c in classes:
                    if c.startswith('typo-') and c in class_to_util:
                        util_found = class_to_util[c]
                        break
            if util_found:
                target_utils.add(util_found)
            if not target_utils:
                continue
            added = False
            new_classes = classes[:]
            for u in sorted(target_utils):
                if u not in new_classes:
                    new_classes.append(u)
                    added = True
            if not added:
                continue
            new_cls = ' '.join(new_classes)
            new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
            new_tag = f"<{m.group(1)}{new_attrs}>"
            edits.append((m.start(), m.end(), new_tag))
        if edits:
            edits.sort(reverse=True)
            for s, e, rep in edits:
                out = out[:s] + rep + out[e:]
            bak = hp.with_suffix(hp.suffix + '.color_util.bak')
            if not bak.exists():
                bak.write_text(text, encoding='utf-8')
            hp.write_text(out, encoding='utf-8')
            changed_files += 1
    return changed_files


def remove_color_from_typos(css_path: Path) -> int:
    css = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    if not css:
        return 0
    orig = css
    def repl_block(m: re.Match) -> str:
        sel = (m.group(1) or '').strip()
        body = (m.group(2) or '').strip()
        sels = [s.strip() for s in sel.split(',') if s.strip()]
        if not any(('.typo-' in s) or (s.startswith(':where(.typo-')) for s in sels):
            return m.group(0)
        # filter out color declarations
        new_decls = []
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            if k.strip().lower() == 'color':
                continue
            new_decls.append(k.strip() + ':' + v.strip())
        return (sel + '{' + ('; '.join(new_decls)) + (';' if new_decls else '') + '}')
    css2 = re.sub(r"([^{}]+)\{([^}]*)\}", repl_block, css)
    if css2 != orig:
        bak = css_path.with_suffix(css_path.suffix + '.typo_no_color.bak')
        if not bak.exists():
            bak.write_text(orig, encoding='utf-8')
        css_path.write_text(css2, encoding='utf-8')
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description='Promote text colors from typo-/n-* into tc-* utilities and annotate HTML')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    sc_path = root / 'style-common.css'
    css = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    cmap = parse_css_map(css)
    # Fallback: if typo-* colors are missing (already stripped), parse backup to recover original role colors
    bak_path = css_path.with_suffix(css_path.suffix + '.typo_no_color.bak')
    if bak_path.exists():
        bak_css = bak_path.read_text(encoding='utf-8', errors='ignore')
        bak_map = parse_css_map(bak_css)
        for cls, kv in bak_map.items():
            if not cls.startswith('typo-'):
                continue
            if 'color' in kv and 'color' not in (cmap.get(cls) or {}):
                cmap.setdefault(cls, {})['color'] = kv['color']

    # Build util per color found in n-* only (do not annotate from role by default)
    class_to_util: Dict[str, str] = {}
    util_defs: Dict[str, str] = {}
    n_color_classes: set[str] = set()
    for cls, kv in cmap.items():
        if not cls.startswith('n-'):
            continue
        col = kv.get('color')
        if not col:
            continue
        util, css_val = util_name_for_color(col)
        class_to_util[cls] = util
        util_defs[util] = css_val
        n_color_classes.add(cls)

    if not util_defs:
        print('[COLOR-UTIL] no colors to promote from typo-/n-*')
    else:
        created = 0
        for util, css_val in sorted(util_defs.items()):
            if ensure_util(sc_path, util, css_val):
                created += 1
        # Annotate HTML with tc-* for n-* sources
        changed = annotate_html(root, class_to_util)
        print(f'[COLOR-UTIL] utils_created={created}, html_files_annotated={changed}, color_classes={len(class_to_util)}')

    # Remove color from all .typo-* rules (role tokens become colorless)
    removed = remove_color_from_typos(css_path)
    if removed:
        print('[COLOR-UTIL] removed color from typo-* rules')

    # Cleanup: remove tc-* injected purely from role colors (earlier runs)
    # We use the backup css (with role colors) to detect role->util mapping, then remove matching tc-* on elements
    # that do NOT carry any n-* with color on them.
    bak_path = css_path.with_suffix(css_path.suffix + '.typo_no_color.bak')
    if bak_path.exists():
        bak_css = bak_path.read_text(encoding='utf-8', errors='ignore')
        bak_map = parse_css_map(bak_css)
        role_to_util: Dict[str, str] = {}
        for cls, kv in bak_map.items():
            if not cls.startswith('typo-'):
                continue
            col = kv.get('color')
            if not col:
                continue
            util, _ = util_name_for_color(col)
            role_to_util[cls] = util
        if role_to_util:
            # Remove role-derived tc-* where element has no n-* color class
            tag_re = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*)>", re.I)
            class_re = re.compile(r'class=\"([^\"]+)\"')
            for hp in root.rglob('*.html'):
                text = hp.read_text(encoding='utf-8', errors='ignore')
                out = text
                edits = []
                for m in tag_re.finditer(text):
                    attrs = m.group(2)
                    cm = class_re.search(attrs)
                    if not cm:
                        continue
                    classes = cm.group(1).split()
                    # skip if any n-* with color present on the element
                    if any((c in n_color_classes) for c in classes):
                        continue
                    role_utils = set()
                    # collect role-derived util candidates present on element
                    for c in classes:
                        if c.startswith('typo-'):
                            u = role_to_util.get(c)
                            if u and (u in classes):
                                role_utils.add(u)
                    if not role_utils:
                        continue
                    new_classes = [c for c in classes if c not in role_utils]
                    if new_classes == classes:
                        continue
                    new_cls = ' '.join(new_classes)
                    new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
                    new_tag = f"<{m.group(1)}{new_attrs}>"
                    edits.append((m.start(), m.end(), new_tag))
                if edits:
                    edits.sort(reverse=True)
                    for s, e, rep in edits:
                        out = out[:s] + rep + out[e:]
                    bak = hp.with_suffix(hp.suffix + '.color_util_cleanup.bak')
                    if not bak.exists():
                        bak.write_text(text, encoding='utf-8')
                    hp.write_text(out, encoding='utf-8')
            print('[COLOR-UTIL] removed role-derived tc-* from HTML where no n-* color existed')


if __name__ == '__main__':
    main()
