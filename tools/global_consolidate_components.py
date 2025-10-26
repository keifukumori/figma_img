#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


WHITELIST = {
    'display','flex-direction','gap','justify-content','align-items','flex-wrap',
    'padding','padding-top','padding-right','padding-bottom','padding-left',
    'min-width', 'min-height',
    'background-color','box-shadow','border-radius','overflow'
}


def parse_css_classes(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    # .class { ... }
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text):
        sels = m.group(1)
        body = m.group(2)
        kv: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if k in WHITELIST:
                kv[k] = v
        if not kv:
            continue
        for cls in sels.split(','):
            cls = cls.strip()
            if cls.startswith('.'):
                d = cmap.setdefault(cls[1:], {})
                d.update(kv)
    # :where(.class){...}
    for m in re.finditer(r":where\(\.(?P<cls>[a-zA-Z0-9_-]+)\)\s*\{([^}]*)\}", css_text):
        sel = m.group('cls')
        body = m.group(2)
        kv: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if k in WHITELIST:
                kv[k] = v
        if kv:
            d = cmap.setdefault(sel, {})
            d.update(kv)
    return cmap


def q_px(val: str) -> str:
    m = re.search(r"(-?\d+)", val or '')
    if not m:
        return val
    n = int(m.group(1))
    scales = [4,6,8,10,12,16,20,24,32,40,48,80,120,420]
    q = min(scales, key=lambda s: abs(s-n))
    return f"{q}px"


def normalize_props(kv: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in kv.items():
        if k in ('gap','padding','padding-top','padding-right','padding-bottom','padding-left','min-width','min-height'):
            out[k] = q_px(v)
        elif k in ('justify-content','align-items','flex-wrap','flex-direction','display','overflow','background-color','box-shadow','border-radius'):
            out[k] = v
    return out


def base_signature(kv: Dict[str, str]) -> Tuple:
    # exclude justify-content differences from base signature（差分は派生で表現）
    base = {k: v for k, v in kv.items() if k != 'justify-content'}
    return tuple(sorted(normalize_props(base).items()))


def intersection_props(dicts: List[Dict[str, str]]) -> Dict[str, str]:
    if not dicts:
        return {}
    keys = set(dicts[0].keys())
    for d in dicts[1:]:
        keys &= set(d.keys())
    out: Dict[str, str] = {}
    for k in sorted(keys):
        v0 = dicts[0].get(k)
        if all(d.get(k) == v0 for d in dicts[1:]):
            out[k] = v0
    return normalize_props(out)


def find_section_for_n(html_text: str, ncls: str) -> str | None:
    # heuristic: find first occurrence and scan upward for enclosing <section class="...">
    # simple approach: nearest previous <section class="...">
    lines = html_text.splitlines()
    pat = re.compile(rf"\b{re.escape(ncls)}\b")
    sec_re = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"", re.I)
    for i, line in enumerate(lines):
        if pat.search(line):
            # search backward
            j = i
            while j >= 0:
                ms = sec_re.search(lines[j])
                if ms:
                    classes = ms.group(1).split()
                    return classes[0] if classes else None
                j -= 1
            break
    return None


def append_rule(style_common: Path, selector: str, props: Dict[str, str]):
    body = '; '.join(f"{k}: {v}" for k, v in sorted(props.items()))
    rule = f"\n:where(.{selector}){{ {body} }}\n"
    css = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
    if rule not in css:
        with style_common.open('a', encoding='utf-8') as f:
            f.write(rule)


def main():
    ap = argparse.ArgumentParser(description='Globally consolidate n-* classes with similar props into section-scoped BEM aliases + derived modifiers')
    ap.add_argument('--root', required=True)
    ap.add_argument('--min-count', type=int, default=2)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    sc_path = root / 'style-common.css'
    css_text = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    cmap = parse_css_classes(css_text)

    # collect n-* classes present in HTML and group by (section, base_signature)
    clusters: Dict[Tuple[str,str], List[str]] = {}
    n_to_section: Dict[str, str] = {}
    html_text = ''
    for hp in root.rglob('*.html'):
        html_text = hp.read_text(encoding='utf-8', errors='ignore')
        for m in re.finditer(r'class=\"([^\"]+)\"', html_text):
            classes = m.group(1).split()
            for c in classes:
                if c.startswith('n-'):
                    sec = n_to_section.get(c) or find_section_for_n(html_text, c) or 'section'
                    n_to_section[c] = sec
                    props = normalize_props(cmap.get(c) or {})
                    sig = base_signature(props)
                    key = (sec, str(sig))
                    arr = clusters.setdefault(key, [])
                    if c not in arr:
                        arr.append(c)

    # consolidate clusters with >= min_count
    total_alias = 0
    for key, nlist in clusters.items():
        if len(nlist) < args.min_count:
            continue
        sec, _ = key
        # intersection props across cluster members
        props_list = [normalize_props(cmap.get(n) or {}) for n in nlist]
        inter = intersection_props(props_list)
        if not inter:
            continue
        # emit alias
        alias = f"{sec}__row-item"
        append_rule(sc_path, alias, inter)
        # append alias to HTML elements that carry these n- classes
        for hp in root.rglob('*.html'):
            text = hp.read_text(encoding='utf-8', errors='ignore')
            orig = text
            def repl(m: re.Match) -> str:
                before, classes, after = m.group(1), m.group(2), m.group(3)
                arr = classes.split()
                have = set(arr)
                if any(n in have for n in nlist) and alias not in have:
                    arr.append(alias)
                    return before + ' '.join(arr) + after
                return m.group(0)
            text2 = re.sub(r'(class=\")([^\"]+)(\")', repl, text)
            if text2 != text:
                if args.backup:
                    hp.with_suffix(hp.suffix + '.gcon.bak').write_text(text, encoding='utf-8')
                hp.write_text(text2, encoding='utf-8')
        total_alias += 1
    print(f"[GLOBAL-CONSOLIDATE] aliases={total_alias}")


if __name__ == '__main__':
    main()

