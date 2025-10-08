#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict, Tuple


SAFE_PROPS = {
    'display', 'flex-direction', 'gap', 'justify-content', 'align-items', 'flex-wrap',
    'align-self', 'min-width', 'width'
}


def util_name_from(decls: Dict[str, str]) -> str:
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
        # fallback: signature-based
        sig = ';'.join(sorted([f"{k}:{v}" for k, v in decls.items()]))
        return 'u-sign-' + str(abs(hash(sig)) % 10**8)
    return 'u-' + '-'.join(toks)


def parse_css_map(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css_text):
        sels = m.group(1)
        body = m.group(2)
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip())
            decls[k] = v
        if not decls:
            continue
        for cls in re.findall(r"\.([a-zA-Z0-9_-]+)", sels):
            d = cmap.setdefault(cls, {})
            d.update(decls)
    return cmap


def main():
    ap = argparse.ArgumentParser(description='Apply u-* utilities based on coverage_report to cover .n-* layout props')
    ap.add_argument('--root', required=True, help='Project root containing index.html, style.css, coverage_report.json')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    css_path = root / 'style.css'
    html_path = root / 'index.html'
    cov_path = root / 'coverage_report.json'
    if not (css_path.exists() and html_path.exists() and cov_path.exists()):
        raise SystemExit('Missing required files in --root')

    cov = json.loads(cov_path.read_text(encoding='utf-8'))
    findings = [f for f in cov.get('findings', []) if f.get('status') == 'needs_keep']
    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    css_map = parse_css_map(css_text)

    # Build desired utilities
    desired: Dict[str, Tuple[Dict[str, str], set]] = {}
    for f in findings:
        ncls = f.get('n_class'); nprops = f.get('n_props_checked') or {}
        decls = {}
        for k, v in nprops.items():
            kl = k.lower()
            if kl not in SAFE_PROPS:
                continue
            # width policy: keep only 100%
            if kl == 'width' and v.lower() != '100%':
                continue
            decls[kl] = v
        if not decls:
            continue
        uname = util_name_from(decls)
        desired.setdefault(uname, (decls, set()))[1].add(ncls)

    # Append missing util CSS
    css_append = []
    for uname, (decls, _) in desired.items():
        if uname not in css_map:
            body = '; '.join([f"{k}: {v}" for k, v in sorted(decls.items())])
            css_append.append(f":where(.{uname}) {{ {body}; }}")
            css_map[uname] = decls

    # Annotate HTML: add util to elements having those n- classes
    html_text = html_path.read_text(encoding='utf-8', errors='ignore')
    total_added = 0
    for uname, (_, nset) in desired.items():
        for ncls in nset:
            patt = re.compile(rf'(\bclass=\"[^\"]*?\b){re.escape(ncls)}(\b[^\"]*\")')
            def repl(m: re.Match):
                nonlocal total_added
                before, after = m.group(1), m.group(2)
                # if util already present in same attribute, skip
                full = (before + ncls + after).rstrip('"')
                if re.search(rf'\b{re.escape(uname)}\b', full):
                    return m.group(0)
                total_added += 1
                return before + ncls + ' ' + uname + after
            html_text = patt.sub(repl, html_text)

    if args.dry_run:
        print(f"[APPLY-U] would append {len(css_append)} util rules; annotate {total_added} occurrences")
        return

    if css_append:
        bak = root / 'style.css.apply_u.bak'
        if not bak.exists():
            bak.write_text(css_text, encoding='utf-8')
        with css_path.open('a', encoding='utf-8') as f:
            f.write('\n\n/* === Auto-generated coverage utilities === */\n')
            for rule in css_append:
                f.write(rule + '\n')

    if total_added:
        bakh = root / 'index.html.apply_u.bak'
        orig = (root / 'index.html').read_text(encoding='utf-8', errors='ignore')
        if not bakh.exists():
            bakh.write_text(orig, encoding='utf-8')
        html_path.write_text(html_text, encoding='utf-8')

    print(f"[APPLY-U] appended {len(css_append)} util rules; annotated {total_added} occurrences")


if __name__ == '__main__':
    main()

