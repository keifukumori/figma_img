#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def png_size(path: Path) -> tuple[int,int] | None:
    try:
        with path.open('rb') as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None
            _len = f.read(4); _typ = f.read(4)
            if _typ != b'IHDR':
                return None
            data = f.read(13)
            if len(data) != 13:
                return None
            w = int.from_bytes(data[0:4], 'big')
            h = int.from_bytes(data[4:8], 'big')
            return (w,h)
    except Exception:
        return None


def compute_weights(seg_html: str, html_dir: Path) -> tuple[int,int]:
    img_re = re.compile(r'<img[^>]*\bsrc=\"([^\"]+)\"', re.I)
    txt_re = re.compile(r"<h[1-6]\\b|<p\\b|figma-style-", re.I)
    weights = []
    has_text = []
    for seg in seg_html.split('\x00'):
        m = img_re.search(seg)
        w = None
        if m:
            src = m.group(1)
            p = (html_dir / src).resolve()
            if p.suffix.lower() == '.png':
                sz = png_size(p)
                if sz:
                    w = sz[0]
        if w is None:
            # fallback: text length
            w = len(re.sub(r"<[^>]+>", "", seg))
        weights.append(w)
        has_text.append(bool(txt_re.search(seg)))
    return (weights[0], weights[1])


def audit_file(path: Path, near_equal_low=0.8, near_equal_high=1.25):
    text = path.read_text(encoding='utf-8', errors='ignore')
    parent_open = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    child_open = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    lines = text.splitlines()
    i = 0
    entries = []
    while i < len(lines):
        m = parent_open.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
        child_idxs = []
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_open.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                child_idxs.append(j)
            j += 1
        if len(child_idxs) == 2:
            s0 = "\n".join(lines[child_idxs[0]: child_idxs[1]])
            s1 = "\n".join(lines[child_idxs[1]: j])
            w0, w1 = compute_weights(s0 + '\x00' + s1, path.parent)
            ratio = (max(w0,w1) / max(1, min(w0,w1)))
            has_span = ('__span-2' in classes) or ('__span-3' in classes) or ('__span-2' in s0) or ('__span-2' in s1) or ('__span-3' in s0) or ('__span-3' in s1)
            near_equal = (near_equal_low <= (w0/max(1,w1)) <= near_equal_high) or (near_equal_low <= (w1/max(1,w0)) <= near_equal_high)
            entries.append({
                'line': i+1,
                'classes': classes,
                'weights': [w0, w1],
                'ratio': round(ratio,2),
                'has_span': has_span,
                'near_equal': near_equal,
            })
        i = j if j > i else i + 1
    return entries


def main():
    ap = argparse.ArgumentParser(description='Audit eq-cols rows and report if equalization looks unintended (ratio and span presence)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--out', default='eqcols_audit.json')
    args = ap.parse_args()

    root = Path(args.root)
    report = {}
    for hp in root.rglob('*.html'):
        entries = audit_file(hp)
        if entries:
            report[str(hp.relative_to(root))] = entries
    (root/args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"[EQCOLS-AUDIT] wrote {args.out} with {sum(len(v) for v in report.values())} rows")


if __name__ == '__main__':
    main()

