#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Tuple


OPEN_TAG_RE = re.compile(r"<([a-zA-Z][a-zA-Z0-9-]*)([^>]*?)>", re.I)
CLASS_RE = re.compile(r"class=\"([^\"]+)\"")
SECTION_RE = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"", re.I)


def nearest_section(lines: List[str], up_to_idx: int) -> str | None:
    j = up_to_idx
    while j >= 0:
        m = SECTION_RE.search(lines[j])
        if m:
            classes = m.group(1).split()
            return classes[0] if classes else None
        j -= 1
    return None


def parse_css_class_props(css_text: str) -> dict[str, dict[str, str]]:
    cmap: dict[str, dict[str, str]] = {}
    # .class { ... }
    for m in re.finditer(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]*)\}", css_text or ""):
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
    for m in re.finditer(r":where\(\.(?P<cls>[a-zA-Z0-9_-]+)\)\s*\{([^}]*)\}", css_text or ""):
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


def analyze_css_usage(css_text: str) -> dict[str, dict[str, bool]]:
    css = re.sub(r"/\*.*?\*/", "", css_text or "", flags=re.S)
    usage: dict[str, dict[str, bool]] = {}
    i = 0
    n = len(css)
    stack: list[str] = []
    last = 0
    while i < n:
        j_open = css.find('{', i)
        j_close = css.find('}', i)
        if j_open == -1 and j_close == -1:
            break
        if j_close != -1 and (j_open == -1 or j_close < j_open):
            if stack:
                stack.pop()
            i = j_close + 1
            last = i
            continue
        header = css[last:j_open]
        hdr = header.strip()
        if hdr.startswith('@'):
            if hdr.lower().startswith('@media'):
                stack.append('media')
            else:
                stack.append('other')
        else:
            inside_media = any(s == 'media' for s in stack)
            for m in re.finditer(r"\.n-([a-zA-Z0-9_-]+)", hdr):
                ncls = 'n-' + m.group(1)
                info = usage.setdefault(ncls, {'complex': False, 'media': False})
                if inside_media:
                    info['media'] = True
                sels = [s.strip() for s in hdr.split(',') if s.strip()]
                for s in sels:
                    if f'.{ncls}' not in s and f':where(.{ncls})' not in s:
                        continue
                    simple_ok = (s == f'.{ncls}') or (s == f':where(.{ncls})')
                    if not simple_ok:
                        info['complex'] = True
                        break
        i = j_open + 1
        last = i
    return usage


def coverage_from_tokens(tokens: list[str]) -> dict[str, str]:
    cov: dict[str, str] = {}
    for t in tokens:
        if t in ('d-flex', 'fx-row', 'fx-col'):
            cov['display'] = 'flex'
            if t == 'fx-row':
                cov['flex-direction'] = 'row'
            elif t == 'fx-col':
                cov['flex-direction'] = 'column'
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
        elif t == 'card' or t.endswith('__card'):
            cov['background-color'] = '*'
            cov['box-shadow'] = '*'
        elif t == 'min-w-0':
            cov['min-width'] = '0'
        elif t == 'min-h-0':
            cov['min-height'] = '0'
    return cov


def missing_props(kv: dict[str, str], cov: dict[str, str]) -> List[str]:
    miss: List[str] = []
    for k, v in kv.items():
        if k.startswith('--'):
            continue
        if k in ('max-width','max-height','transform','transform-origin'):
            continue
        if k in ('align-self','height'):
            continue
        if k == 'justify-content' and v.strip() == 'flex-start':
            continue
        if k == 'flex-wrap' and v.strip() == 'nowrap':
            continue
        if k == 'gap':
            continue
        if k == 'padding':
            # require any side coverage
            if not any(s in cov for s in ('padding-left','padding-right','padding-top','padding-bottom')):
                miss.append(k)
            continue
        cv = cov.get(k)
        if cv is None:
            miss.append(k)
        elif cv != '*' and v.strip() != cv.strip():
            miss.append(k)
    return miss


def main():
    ap = argparse.ArgumentParser(description='Report why n-* classes are not safe to drop (blockers)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--section', help='Filter to a section key (optional)')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    sc_path = root / 'style-common.css'
    css_text = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    sc_text = sc_path.read_text(encoding='utf-8', errors='ignore') if sc_path.exists() else ''
    cmap = parse_css_class_props(css_text)
    if sc_text:
        cm2 = parse_css_class_props(sc_text)
        for k, v in cm2.items():
            d = cmap.setdefault(k, {})
            d.update(v)
    usage = analyze_css_usage(css_text)

    blockers = []
    n_sections: Dict[str, Counter] = defaultdict(Counter)
    n_aliases: Dict[str, Counter] = defaultdict(Counter)

    for hp in sorted(root.rglob('*.html')):
        lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
        for i, line in enumerate(lines):
            m = OPEN_TAG_RE.search(line)
            if not m:
                continue
            cm = CLASS_RE.search(m.group(2))
            if not cm:
                continue
            classes = cm.group(1).split()
            if args.section:
                sec = nearest_section(lines, i)
                if sec != args.section:
                    continue
            n_tokens = [c for c in classes if c.startswith('n-')]
            if not n_tokens:
                continue
            cov = coverage_from_tokens(classes)
            # add props from classes present (alias, utilities)
            for c in classes:
                kv_c = cmap.get(c)
                if kv_c:
                    if 'padding' in kv_c:
                        parts = re.split(r"\s+", kv_c['padding'])
                        nums = [p for p in parts if p]
                        if len(nums) == 1:
                            cov['padding-top'] = nums[0]; cov['padding-right'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[0]
                        elif len(nums) == 2:
                            cov['padding-top'] = nums[0]; cov['padding-bottom'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]
                        elif len(nums) == 3:
                            cov['padding-top'] = nums[0]; cov['padding-left'] = nums[1]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]
                        elif len(nums) >= 4:
                            cov['padding-top'] = nums[0]; cov['padding-right'] = nums[1]; cov['padding-bottom'] = nums[2]; cov['padding-left'] = nums[3]
                    for k, v in kv_c.items():
                        if k == 'padding':
                            continue
                        cov[k] = v
            # alias context on same element
            sec_here = nearest_section(lines, i) or 'section'
            alias_here = [c for c in classes if '__' in c and (c.startswith(sec_here + '__') or c.endswith('__row-item') or c.endswith('__card'))]

            for ncls in n_tokens:
                n_sections[ncls][sec_here] += 1
                for al in alias_here:
                    n_aliases[ncls][al] += 1
                kv = cmap.get(ncls) or {}
                miss = missing_props(kv, cov) if kv else []
                info = usage.get(ncls) or {'complex': False, 'media': False}
                blockers.append({
                    'file': str(hp.relative_to(root)),
                    'line_index': i,
                    'section': sec_here,
                    'n_class': ncls,
                    'alias_context': alias_here,
                    'missing_props': miss,
                    'selector_complex': bool(info.get('complex')),
                    'selector_media': bool(info.get('media')),
                })

    # Aggregate
    summary: Dict[str, dict] = {}
    for b in blockers:
        rec = summary.setdefault(b['n_class'], {
            'sections': Counter(),
            'alias_contexts': Counter(),
            'missing_props': Counter(),
            'selector_complex': False,
            'selector_media': False,
        })
        rec['sections'][b['section']] += 1
        for al in b['alias_context']:
            rec['alias_contexts'][al] += 1
        for p in b['missing_props']:
            rec['missing_props'][p] += 1
        rec['selector_complex'] = rec['selector_complex'] or b['selector_complex']
        rec['selector_media'] = rec['selector_media'] or b['selector_media']

    out = {
        'by_class': {
            k: {
                'sections': dict(v['sections']),
                'alias_contexts': dict(v['alias_contexts']),
                'missing_props': dict(v['missing_props']),
                'selector_complex': v['selector_complex'],
                'selector_media': v['selector_media'],
            } for k, v in summary.items()
        },
        'total_n_classes': len(summary),
    }
    (root / 'n_drop_blockers.json').write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[BLOCKERS] n_classes={len(summary)} written={root/'n_drop_blockers.json'}")


if __name__ == '__main__':
    main()
