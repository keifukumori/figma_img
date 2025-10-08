#!/usr/bin/env python3
"""
Unify duplicate .n-<id> CSS rules by introducing shared utility classes and annotating HTML.

Safe strategy:
 - Consider only a whitelist of layout props (flex row/col, gap, justify/align, flex-wrap, width, align-self)
 - Build declaration signatures from style.css base rules (no @media)
 - For signatures used by 2+ .n- classes, generate a utility class name and append a rule
 - Annotate index.html elements that carry those .n- classes with the utility class (keep .n- for back-compat)

This script is conservative and idempotent; it does not remove existing rules.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path


PROP_WHITELIST = {
    'display', 'flex-direction', 'gap', 'justify-content', 'align-items', 'flex-wrap',
    # width is intentionally handled specially (see quantize_decls)
    'width', 'align-self', 'min-width', 'max-width',
    # optional (quantization-friendly)
    'border-radius', 'font-size',
}

# Quantization policy (conservative defaults)
QUANT = {
    # spacing/layout
    'gap': {'step_px': 4, 'max_dev_px': 2},
    # visuals
    'border-radius': {'step_px': 2, 'max_dev_px': 1},
    # typography (allowed set, then snap)
    'font-size': {'allowed': [12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 44]},
}

def _px_int(v: str) -> int | None:
    try:
        if isinstance(v, (int, float)):
            return int(round(float(v)))
        v = str(v).strip()
        if v.endswith('px'):
            return int(round(float(v[:-2])))
        # plain number treated as px
        return int(round(float(v)))
    except Exception:
        return None

def _quantize_px(value_px: int, step_px: int, max_dev_px: int) -> int:
    # Round to nearest step if within max_dev, else keep original
    snapped = int(round(value_px / step_px) * step_px)
    return snapped if abs(value_px - snapped) <= max_dev_px else value_px

def quantize_decls(decls: dict) -> dict:
    out = dict(decls)
    # gap
    if 'gap' in out:
        px = _px_int(out['gap'])
        if px is not None:
            cfg = QUANT.get('gap', {})
            px2 = _quantize_px(px, cfg.get('step_px', 4), cfg.get('max_dev_px', 2))
            out['gap'] = f"{px2}px"
    # border-radius
    if 'border-radius' in out:
        px = _px_int(out['border-radius'])
        if px is not None:
            cfg = QUANT.get('border-radius', {})
            px2 = _quantize_px(px, cfg.get('step_px', 2), cfg.get('max_dev_px', 1))
            out['border-radius'] = f"{px2}px"
    # font-size
    if 'font-size' in out:
        px = _px_int(out['font-size'])
        allowed = QUANT.get('font-size', {}).get('allowed') or []
        if px is not None and allowed:
            # snap to nearest allowed if within ±1px, else keep
            nearest = min(allowed, key=lambda a: abs(a-px))
            out['font-size'] = f"{nearest}px" if abs(nearest - px) <= 1 else f"{px}px"
    # Width handling policy (robustness-first):
    # - Drop width:auto entirely (no-op in signatures)
    # - Keep only width:100% as a safe, reusable utility signal
    # - Drop any other explicit width (e.g., 5px/349px) to avoid leaking element-specific
    #   sizes into shared utilities that would accidentally constrain many nodes.
    w = (out.get('width') or '').strip().lower()
    if w == 'auto':
        out.pop('width', None)
    elif w and w != '100%':
        out.pop('width', None)
    return out


def parse_css_rules(css_text: str):
    # naive parser: .class { decl }
    rules = []
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text):
        sel = m.group(1)
        body = m.group(2)
        decls = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower()
            v = re.sub(r"\s+", ' ', v.strip())
            if k in PROP_WHITELIST:
                decls[k] = v
        if decls:
            rules.append((sel, decls))
    return rules


def signature(decls: dict) -> str:
    items = sorted(decls.items())
    return ';'.join([f"{k}:{v}" for k, v in items])


def util_name_from(decls: dict) -> str:
    """Short-code utility naming.
    direction: row=r, column=c; gap: g{px}; justify: js/jc/je/jb/ja/jv;
    align-items: as/ac/ae/at; wrap: w/nw; width: w100 only
    Example: u-r-g40-js-as
    """
    toks = []
    if decls.get('display') == 'flex':
        fd = decls.get('flex-direction')
        if fd == 'row':
            toks.append('r')
        elif fd == 'column':
            toks.append('c')
        g = decls.get('gap')
        if g and re.match(r"\d+px", g):
            toks.append('g' + re.findall(r"\d+", g)[0])
        jc_map = {
            'flex-start': 'js', 'center': 'jc', 'flex-end': 'je',
            'space-between': 'jb', 'space-around': 'ja', 'space-evenly': 'jv'
        }
        jc = decls.get('justify-content')
        if jc in jc_map:
            toks.append(jc_map[jc])
        ai_map = {
            'flex-start': 'as', 'center': 'ac', 'flex-end': 'ae', 'stretch': 'at'
        }
        ai = decls.get('align-items')
        if ai in ai_map:
            toks.append(ai_map[ai])
        fw = decls.get('flex-wrap')
        if fw == 'wrap':
            toks.append('w')
        elif fw == 'nowrap':
            toks.append('nw')
    if decls.get('width') == '100%':
        toks.append('w100')
    if not toks:
        return 'u-sign-' + str(abs(hash(signature(decls))) % 10**8)
    return 'u-' + '-'.join(toks)


def append_utils_to_css(css_path: Path, util_map: dict[str, dict]):
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    out = [css.rstrip(), '\n\n/* === Unified utility classes (auto-generated) === */']
    for uname, decls in util_map.items():
        body = '; '.join([f"{k}: {v}" for k, v in sorted(decls.items())])
        rule = f"\n:where(.{uname}) {{ {body}; }}\n"
        if f".{uname}" not in css:
            out.append(rule)
    css_path.write_text('\n'.join(out) + '\n', encoding='utf-8')


def annotate_html(html_path: Path, class_to_util: dict[str, str]):
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    # build regex to find class="..."
    def add_util(m: re.Match) -> str:
        classes = m.group(1)
        arr = classes.split()
        extra = set()
        for c in arr:
            if c in class_to_util:
                extra.add(class_to_util[c])
        if not extra:
            return m.group(0)
        # avoid duplicates
        for e in sorted(extra):
            if e not in arr:
                arr.append(e)
        return f'class="{" ".join(arr)}"'

    new = re.sub(r'class=\"([^\"]+)\"', add_util, text)
    if new != text:
        html_path.write_text(new, encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description='Unify duplicate .n-* rules into utility classes and annotate HTML')
    ap.add_argument('--root', required=True, help='Project root (contains style.css and index.html)')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    html_path = root / 'index.html'
    if not css_path.exists() or not html_path.exists():
        raise SystemExit('Missing style.css or index.html in root')

    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    rules = parse_css_rules(css_text)
    bucket: dict[str, list[str]] = {}
    sig_to_decls: dict[str, dict] = {}
    for sel, decls in rules:
        if not sel.startswith('.'):
            continue
        if not re.match(r"^\.[a-zA-Z0-9_-]+$", sel):
            continue
        if not sel.startswith('.n-'):
            continue
        q = quantize_decls(decls)
        sig = signature(q)
        if not sig:
            continue
        bucket.setdefault(sig, []).append(sel)
        sig_to_decls[sig] = q

    # choose groups with >=2 members
    util_map: dict[str, dict] = {}
    class_to_util: dict[str, str] = {}
    for sig, sels in bucket.items():
        if len(sels) < 2:
            continue
        decls = sig_to_decls[sig]
        uname = util_name_from(decls)
        util_map[uname] = decls
        for s in sels:
            class_to_util[s[1:]] = uname  # strip leading dot

    if util_map:
        append_utils_to_css(css_path, util_map)
        annotate_html(html_path, class_to_util)

    print(f"[UNIFY] groups: {sum(1 for _ in util_map)}, classes annotated: {len(class_to_util)}")


if __name__ == '__main__':
    main()
