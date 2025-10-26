#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def parse_css_class_props(css_text: str) -> dict[str, dict[str, str]]:
    cmap: dict[str, dict[str, str]] = {}
    # .class { ... } and multi-selectors
    for m in re.finditer(r"(\.[a-zA-Z0-9_-][^\{,\s]*)\s*(?:,\s*\.[a-zA-Z0-9_-][^\{,\s]*)*\s*\{([^}]*)\}", css_text):
        selectors = m.group(0).split('{',1)[0]
        body = m.group(2)
        kv: dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k,v = part.split(':',1)
            k=k.strip().lower(); v=re.sub(r"\s+"," ", v.strip().lower())
            if k:
                kv[k]=v
        if not kv:
            continue
        for s in selectors.split(','):
            s=s.strip()
            if s.startswith('.'):
                cmap.setdefault(s[1:],{}).update(kv)
    # :where(.class) { ... }
    for m in re.finditer(r":where\(\.(?P<cls>[a-zA-Z0-9_-]+)\)\s*\{([^}]*)\}", css_text):
        sel = m.group('cls')
        body = m.group(2)
        kv: dict[str,str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k,v = part.split(':',1)
            k=k.strip().lower(); v=re.sub(r"\s+"," ", v.strip().lower())
            if k:
                kv[k]=v
        if kv:
            d = cmap.setdefault(sel,{})
            d.update(kv)
    return cmap


def coverage_from_tokens(tokens: list[str]) -> dict[str, str]:
    cov: dict[str, str] = {}
    for t in tokens:
        if t in ('d-flex','fx-row','fx-col'):
            cov['display']='flex'; cov['flex-direction']='row' if t=='fx-row' else ('column' if t=='fx-col' else cov.get('flex-direction','row'))
        elif t.startswith('g-'):
            try:
                cov['gap']=f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('ai-'):
            cov['align-items']=t[3:].replace('-',' ')
        elif t.startswith('jc-'):
            cov['justify-content']=t[3:].replace('-',' ')
        elif t.startswith('fw-'):
            cov['flex-wrap']=t[3:].replace('-',' ')
        elif t=='w-full':
            cov['width']='100%'
        elif t=='w-auto':
            cov['width']='auto'
        elif t=='h-full':
            cov['height']='100%'
        elif t=='h-auto':
            cov['height']='auto'
        elif t=='min-w-0':
            cov['min-width']='0'
        elif t=='min-h-0':
            cov['min-height']='0'
        elif t.startswith('px-'):
            try:
                n=int(t.split('-',1)[1]); cov['padding-left']=f'{n}px'; cov['padding-right']=f'{n}px'
            except Exception:
                pass
        elif t.startswith('py-'):
            try:
                n=int(t.split('-',1)[1]); cov['padding-top']=f'{n}px'; cov['padding-bottom']=f'{n}px'
            except Exception:
                pass
        elif t.startswith('pt-'):
            try:
                cov['padding-top']=f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pb-'):
            try:
                cov['padding-bottom']=f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pl-'):
            try:
                cov['padding-left']=f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
        elif t.startswith('pr-'):
            try:
                cov['padding-right']=f"{int(t.split('-',1)[1])}px"
            except Exception:
                pass
    return cov


def missing_props(n_props: dict[str,str], cov: dict[str,str]) -> list[str]:
    missing: list[str] = []
    for k,v in n_props.items():
        # ignore custom props and transforms from coverage consideration
        if k.startswith('--'):
            continue
        if k in ('max-width','max-height','transform','transform-origin'):
            missing.append(k)
            continue
        if k=='padding':
            # require any side presence
            if not any(s in cov for s in ('padding-left','padding-right','padding-top','padding-bottom')):
                missing.append(k)
            continue
        cv = cov.get(k)
        if cv is None:
            missing.append(k)
        else:
            if cv.strip() != v.strip() and cv != '*':
                missing.append(k)
    return missing


def analyze_visuals_eq_cols(html_text: str, css_map: dict[str,dict[str,str]]):
    lines = html_text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    visuals = {'background-color','box-shadow','border-radius'}
    i=0
    out=[]
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i+=1; continue
        indent = m.group(1)
        close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
        kids=[]
        j=i+1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                kids.append(cm.group(3))
            j+=1
        if kids:
            # collect n-* props
            props_list=[]
            for cls in kids:
                ns=[c for c in cls.split() if c.startswith('n-')]
                merged={}
                for n in ns:
                    kv = css_map.get(n) or {}
                    for k in visuals:
                        v = kv.get(k)
                        if v is not None:
                            merged[k]=v
                if merged:
                    props_list.append(merged)
            if props_list:
                keys=set.intersection(*[set(d.keys()) for d in props_list]) if props_list else set()
                common={}
                for k in sorted(keys):
                    v0 = props_list[0].get(k)
                    if all(d.get(k)==v0 for d in props_list[1:]):
                        common[k]=v0
                if common:
                    out.append(common)
        i=j if j>i else i+1
    return out


def main():
    ap = argparse.ArgumentParser(description='Emit residuals report for n-* drops and optional visuals candidates')
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', default='residuals.json')
    ap.add_argument('--visuals', action='store_true', help='Also analyze eq-cols rows for common visuals')
    args = ap.parse_args()

    root = Path(args.root)
    css_text = (root/'style.css').read_text(encoding='utf-8', errors='ignore') if (root/'style.css').exists() else ''
    sc_text = (root/'style-common.css').read_text(encoding='utf-8', errors='ignore') if (root/'style-common.css').exists() else ''
    css_map = parse_css_class_props(css_text)
    # merge style-common to coverage map
    cm2 = parse_css_class_props(sc_text)
    for k,v in cm2.items():
        css_map.setdefault(k, {}).update(v)

    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')

    report: dict[str, list] = {}
    summary: dict[str,int] = {}
    visuals_report: dict[str, list] = {}

    for hp in root.rglob('*.html'):
        text = hp.read_text(encoding='utf-8', errors='ignore')
        entries = []
        for m in tag_re.finditer(text):
            attrs = m.group(2)
            cm = class_re.search(attrs)
            if not cm:
                continue
            classes = cm.group(1).split()
            cov = coverage_from_tokens(classes)
            # add coverage from any classes present (alias/BEM etc.)
            for c in classes:
                kv_c = css_map.get(c)
                if kv_c:
                    for k,v in kv_c.items():
                        cov[k]=v
            residuals = []
            for c in classes:
                if c.startswith('n-'):
                    kv = css_map.get(c) or {}
                    if not kv:
                        continue
                    miss = missing_props(kv, cov)
                    if miss:
                        residuals.append({'n': c, 'missing': miss})
                        for k in miss:
                            summary[k] = summary.get(k,0)+1
            if residuals:
                entries.append({'classes': ' '.join(classes), 'residuals': residuals})
        if entries:
            report[str(hp.relative_to(root))] = entries
        if args.visuals:
            vis = analyze_visuals_eq_cols(text, css_map)
            if vis:
                visuals_report[str(hp.relative_to(root))] = vis

    out = {
        'summary': summary,
        'files': report,
    }
    if args.visuals and visuals_report:
        out['visuals_candidates'] = visuals_report

    (root/args.out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[RESIDUALS] wrote {args.out} with {sum(len(v) for v in report.values())} entries")


if __name__ == '__main__':
    main()

