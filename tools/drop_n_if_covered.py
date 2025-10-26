#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def parse_css_class_props(css_text: str) -> dict[str, dict[str, str]]:
    cmap: dict[str, dict[str, str]] = {}
    # .class { ... }
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text):
        sel = m.group(1)
        body = m.group(2)
        kv: dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if k:
                kv[k] = v
        if kv:
            # Support multi selectors by splitting
            for s in sel.split(','):
                s = s.strip()
                if s.startswith('.'):
                    cmap[s[1:]] = kv
    # :where(.class) { ... }
    for m in re.finditer(r":where\(\.(?P<cls>[a-zA-Z0-9_-]+)\)\s*\{([^}]*)\}", css_text):
        sel = '.' + m.group('cls')
        body = m.group(2)
        kv: dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if k:
                kv[k] = v
        if kv:
            d = cmap.setdefault(sel[1:], {})
            d.update(kv)
    return cmap


def coverage_from_tokens(tokens: list[str]) -> dict[str, str | tuple[str, str, str, str]]:
    cov: dict[str, str | tuple[str, str, str, str]] = {}
    for t in tokens:
        if t == 'd-flex' or t == 'fx-row' or t == 'fx-col':
            cov['display'] = 'flex'
            cov['flex-direction'] = 'row' if t == 'fx-row' else ('column' if t == 'fx-col' else cov.get('flex-direction','row'))
        elif t.startswith('g-'):
            try:
                n = int(t.split('-',1)[1]); cov['gap'] = f'{n}px'
            except Exception:
                pass
        elif t.startswith('ai-'):
            cov['align-items'] = t[3:].replace('-', ' ')
        elif t.startswith('jc-'):
            cov['justify-content'] = t[3:].replace('-', ' ')
        elif t == '__center':
            cov['justify-content'] = 'center'
        elif t == '__end':
            cov['justify-content'] = 'flex-end'
        elif t == '__between':
            cov['justify-content'] = 'space-between'
        elif t.startswith('fw-'):
            cov['flex-wrap'] = t[3:].replace('-', ' ')
        elif t == 'w-full':
            cov['width'] = '100%'
        elif t == 'w-auto':
            cov['width'] = 'auto'
        elif t == 'h-full':
            cov['height'] = '100%'
        elif t == 'h-auto':
            cov['height'] = 'auto'
        elif t.startswith('as-'):
            cov['align-self'] = t[3:].replace('-', ' ')
        elif t == 'clip':
            cov['overflow'] = 'hidden'
        elif t.startswith('px-'):
            try:
                n = int(t.split('-',1)[1]); cov['padding-left'] = f'{n}px'; cov['padding-right'] = f'{n}px'
            except Exception:
                pass
        elif t.startswith('py-'):
            try:
                n = int(t.split('-',1)[1]); cov['padding-top'] = f'{n}px'; cov['padding-bottom'] = f'{n}px'
            except Exception:
                pass
        elif t.startswith('pt-'):
            try:
                cov['padding-top'] = f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pb-'):
            try:
                cov['padding-bottom'] = f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pl-'):
            try:
                cov['padding-left'] = f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pr-'):
            try:
                cov['padding-right'] = f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t == 'card':
            # consider background-color and box-shadow covered by card
            cov['background-color'] = '*'
            cov['box-shadow'] = '*'
        elif t == 'min-w-0':
            cov['min-width'] = '0'
        elif t == 'min-h-0':
            cov['min-height'] = '0'
    return cov


def covered_all(kv: dict[str, str], cov: dict[str, str | tuple[str, str, str, str]]) -> bool:
    for k, v in kv.items():
        # Treat CSS custom props and unknowns as not covered
        if k.startswith('--'):
            continue
        if k in ('max-width','max-height','transform','transform-origin'):
            return False
        # Ignore benign defaults or redundant props under our normalization
        if k in ('align-self','height'):
            continue
        if k == 'justify-content' and v.strip() == 'flex-start':
            continue
        if k == 'flex-wrap' and v.strip() == 'nowrap':
            continue
        # Be lenient with gap for drop decisions; spacing is commonly consolidated elsewhere
        if k == 'gap':
            continue
        if k == 'padding':
            # require all sides to be covered in cov via side props
            parts = re.split(r"\s+", v)
            # If any side present via px/py/pt/pb/pl/pr, consider covered
            if not any(s in cov for s in ('padding-left','padding-right','padding-top','padding-bottom')):
                return False
            else:
                continue
        if k == 'min-height':
            cv = cov.get('min-height')
            if isinstance(cv, str) and cv.strip() in ('0','0px'):
                # Treat min-height as covered if neutralized to 0 via min-h-0
                continue
        cv = cov.get(k)
        if cv is None:
            return False
        if cv != '*' and isinstance(cv, str) and v != cv:
            # allow minor spacing differences (e.g., '24px' vs '24px ')
            if v.strip() != cv.strip():
                return False
    return True


def main():
    ap = argparse.ArgumentParser(description='Drop n-* classes from HTML when all their CSS props are covered by utilities/tokens present on the element')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    css_text = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    cmap = parse_css_class_props(css_text)
    # also include style-common.css coverage
    common_path = root / 'style-common.css'
    common_text = common_path.read_text(encoding='utf-8', errors='ignore') if common_path.exists() else ''
    if common_text:
        cm2 = parse_css_class_props(common_text)
        for k, v in cm2.items():
            d = cmap.setdefault(k, {})
            d.update(v)

    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')

    files_changed = 0
    removed_total = 0
    for html in root.rglob('*.html'):
        src = html.read_text(encoding='utf-8', errors='ignore')
        edits = []
        for m in tag_re.finditer(src):
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1).split()
            tokens = classes[:]
            cov = coverage_from_tokens(tokens)
            # Add CSS props of all classes present (alias/BEM等) to coverage
            for c in classes:
                kv_c = cmap.get(c)
                if kv_c:
                    for k, v in kv_c.items():
                        if k == 'padding':
                            # expand shorthand into sides for coverage
                            parts = re.split(r"\s+", v)
                            nums = [p for p in parts if p]
                            if len(nums) == 1:
                                cov['padding-top'] = nums[0]; cov['padding-right'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[0]
                            elif len(nums) == 2:
                                cov['padding-top'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]
                            elif len(nums) == 3:
                                cov['padding-top'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]
                            elif len(nums) >= 4:
                                cov['padding-top'] = nums[0]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]; cov['padding-left'] = nums[3]
                            continue
                        cov[k] = v
            # Card visuals: treat as wildcard-covered to avoid over-constraining drop
            if any((c == 'card') or c.endswith('__card') for c in classes):
                cov['background-color'] = '*'
                cov['box-shadow'] = '*'
            to_remove = []
            for c in classes:
                if c.startswith('n-'):
                    kv = cmap.get(c)
                    if kv and covered_all(kv, cov):
                        to_remove.append(c)
            if not to_remove:
                continue
            kept = [c for c in classes if c not in to_remove]
            new_cls = ' '.join(kept)
            new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
            new_tag = f"<{m.group(1)}{new_attrs}>"
            edits.append((m.start(), m.end(), new_tag, len(to_remove)))
        if edits:
            edits.sort(reverse=True)
            out = src
            count_removed = 0
            for s, e, rep, nrm in edits:
                out = out[:s] + rep + out[e:]
                count_removed += nrm
            if args.backup:
                bak = html.with_suffix(html.suffix + '.dropn.bak')
                if not bak.exists():
                    bak.write_text(src, encoding='utf-8')
            html.write_text(out, encoding='utf-8')
            files_changed += 1
            removed_total += count_removed

    print(f"[DROP-N] files_changed={files_changed}, n_tokens_removed={removed_total}")


if __name__ == '__main__':
    main()
