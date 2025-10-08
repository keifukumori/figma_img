#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Tuple


SAFE_PROPS_LAYOUT = {
    'display', 'flex-direction', 'gap', 'justify-content', 'align-items', 'flex-wrap',
    'align-self', 'min-width', 'max-width',
    # widthは保守的に扱う（100%は許容、それ以外は未カバー扱いに倒す）
    'width',
}
SAFE_PROPS_TYPO = {
    'font-size', 'font-weight', 'line-height', 'letter-spacing', 'text-align'
}


def parse_css_classes(css_text: str) -> Dict[str, Dict[str, str]]:
    """Parse CSS and return a map: class -> {prop: value} (top-level blocks only).
    Supports selectors like .class { ... } and :where(.class) { ... } and multiple selectors.
    Very naive – ignores @media, specificity, and nested constructs – suitable for conservative audit.
    """
    class_map: Dict[str, Dict[str, str]] = {}
    # match blocks "selectors { body }"; do not cross braces
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css_text):
        selectors = m.group(1).strip()
        body = m.group(2)
        # extract any .class occurrences in selectors
        classes = re.findall(r"\.([a-zA-Z0-9_-]+)", selectors)
        if not classes:
            continue
        # parse declarations
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower()
            v = re.sub(r"\s+", ' ', v.strip())
            if not k:
                continue
            decls[k] = v
        if not decls:
            continue
        for cls in classes:
            d = class_map.setdefault(cls, {})
            d.update(decls)
    return class_map


class HTMLClassCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements: List[Tuple[str, List[str]]] = []  # (path, classes)
        self.path_stack: List[str] = []
        self.count_stack: List[int] = [0]

    def _cur_path(self) -> str:
        return ''.join(self.path_stack)

    def handle_starttag(self, tag, attrs):
        self.count_stack[-1] += 1
        idx = self.count_stack[-1]
        # try id/class hint for better debuggability
        attr_d = dict(attrs)
        if 'id' in attr_d and attr_d['id']:
            seg = f"/{tag}#{attr_d['id']}[{idx}]"
        elif 'class' in attr_d and attr_d['class']:
            first = attr_d['class'].split()[0]
            seg = f"/{tag}.{first}[{idx}]"
        else:
            seg = f"/{tag}[{idx}]"
        self.path_stack.append(seg)
        self.count_stack.append(0)
        classes = (attr_d.get('class') or '').split()
        if classes:
            self.elements.append((self._cur_path(), classes))

    def handle_endtag(self, tag):
        if self.count_stack:
            self.count_stack.pop()
        if self.path_stack:
            self.path_stack.pop()


def covered_by_other_classes(n_props: Dict[str, str], other_classes: List[str], css_map: Dict[str, Dict[str, str]]) -> Tuple[bool, Dict[str, List[str]], List[str]]:
    """Return (fully_covered, covering, uncovered_props) for the n-class properties.
    Typography props can be covered by any class (tokens等含む)。
    Layout widthポリシー: widthは100%のみ『カバー可能』とみなし、それ以外のwidthは未カバー扱い。
    """
    covering: Dict[str, List[str]] = {}
    uncovered: List[str] = []
    for prop, val in n_props.items():
        prop_l = prop.lower()
        # Consider only safe props
        if prop_l not in SAFE_PROPS_LAYOUT and prop_l not in SAFE_PROPS_TYPO:
            continue
        # Optional defaults that we treat as already satisfied (do not require explicit covering class)
        if prop_l == 'width':
            v = (val or '').lower()
            if v == 'auto' or v == '':
                continue  # safe default
            if v != '100%':
                # width coverage can be satisfied by explicit width, or by max-width / flex-basis equivalent
                covered_by_equiv = False
                for cls in other_classes:
                    d = css_map.get(cls) or {}
                    if d.get('width', '').lower() == v:
                        covered_by_equiv = True; break
                    if d.get('max-width', '').lower() == v:
                        covered_by_equiv = True; break
                    flex = d.get('flex', '').replace('  ', ' ').strip().lower()
                    if flex and v in flex and ('0 0' in flex or '0 0 ' in flex):
                        covered_by_equiv = True; break
                if covered_by_equiv:
                    continue
                uncovered.append(prop_l)
                continue
        if prop_l == 'min-width' and str(val).strip() in ('0', '0px'):
            continue
        if prop_l == 'flex-wrap' and (str(val).strip().lower() == 'nowrap'):
            continue
        if prop_l == 'display' and (str(val).strip().lower() == 'block'):
            continue
        found = False
        for cls in other_classes:
            d = css_map.get(cls)
            if not d:
                continue
            # exact match of value
            if d.get(prop_l) == val:
                covering.setdefault(prop_l, []).append(cls)
                found = True
                break
        if not found:
            uncovered.append(prop_l)
    return (len(uncovered) == 0, covering, uncovered)


def main():
    ap = argparse.ArgumentParser(description='Audit .n-* coverage by tokens/util/layout for safe HTML prune (report only)')
    ap.add_argument('--root', required=True, help='Project root containing index.html and style.css')
    args = ap.parse_args()

    root = Path(args.root)
    html_path = root / 'index.html'
    css_path = root / 'style.css'
    if not html_path.exists() or not css_path.exists():
        raise SystemExit('Missing style.css or index.html in root')

    css_text = css_path.read_text(encoding='utf-8', errors='ignore')
    css_map = parse_css_classes(css_text)

    html_text = html_path.read_text(encoding='utf-8', errors='ignore')
    collector = HTMLClassCollector()
    collector.feed(html_text)

    findings = []
    total_n = 0
    removable = 0

    for path, classes in collector.elements:
        n_classes = [c for c in classes if c.startswith('n-')]
        if not n_classes:
            continue
        for ncls in n_classes:
            total_n += 1
            nprops = css_map.get(ncls, {})
            # skip if no CSS for this .n-* (can't safely judge)
            if not nprops:
                findings.append({'path': path, 'n_class': ncls, 'status': 'no_rule', 'uncovered': [], 'covering': {}, 'other_classes': classes})
                continue
            others = [c for c in classes if c != ncls]
            full, cov, unc = covered_by_other_classes(nprops, others, css_map)
            status = 'candidate_removable' if full else 'needs_keep'
            if full:
                removable += 1
            findings.append({
                'path': path,
                'n_class': ncls,
                'status': status,
                'uncovered': unc,
                'covering': cov,
                'other_classes': others,
                'n_props_checked': {k: nprops[k] for k in nprops if k in SAFE_PROPS_LAYOUT or k in SAFE_PROPS_TYPO}
            })

    report = {
        'root': str(root),
        'summary': {
            'total_n_in_html': total_n,
            'candidate_removable': removable,
            'needs_keep': total_n - removable,
        },
        'findings': findings,
    }
    out = root / 'coverage_report.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[COVERAGE] Report written: {out}")


if __name__ == '__main__':
    main()
