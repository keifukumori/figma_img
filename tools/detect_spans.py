#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def png_size(path: Path) -> tuple[int,int] | None:
    try:
        with path.open('rb') as f:
            sig = f.read(8)
            if sig != b"\x89PNG\r\n\x1a\n":
                return None
            # IHDR chunk: length(4) type(4) data(13) crc(4)
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


def detect_spans_in_file(html_path: Path, project_root: Path, threshold: float = 1.3, backup: bool = False) -> bool:
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    lines = text.splitlines()
    original = text
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_re_tpl = r"^{indent}</div>\s*$"
    img_re = re.compile(r'<img[^>]*\bsrc=\"([^\"]+)\"', re.I)
    changed = False
    i = 0
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        # collect direct children indices
        child_idxs = []
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                child_idxs.append(j)
            j += 1
        if len(child_idxs) == 2:
            weights = []
            # for each child, scan until next sibling or parent close, find first <img src>
            has_img = [False, False]
            has_text = [False, False]
            for k, idx in enumerate(child_idxs + [j]):
                if k == 2:
                    break
                start = child_idxs[k]
                end = child_idxs[k+1] if k+1 < 2 else j
                # collect segment text
                seg = "\n".join(lines[start:end])
                mw = None
                im = img_re.search(seg)
                if im:
                    src = im.group(1)
                    # normalize path
                    p = (html_path.parent / src).resolve()
                    size = png_size(p) if p.suffix.lower() == '.png' else None
                    if size:
                        mw = size[0]
                        has_img[k] = True
                # detect if segment has text content markers
                if re.search(r"<h[1-6]\\b|<p\\b|figma-style-", seg, re.I):
                    has_text[k] = True
                if mw is None:
                    # fallback: approximate weight via segment length
                    mw = len(re.sub(r"<[^>]+>", "", seg))
                weights.append(mw)
            if len(weights) == 2 and min(weights) > 0:
                a, b = weights
                big = 0 if a >= b else 1
                ratio = max(a,b)/min(a,b)
                # 強化ヒューリスティク: 左が画像(<=360px)・右がテキスト -> 右を大きい側として3:1に寄せる
                if has_img[0] and not has_text[0] and has_text[1] and weights[0] <= 360:
                    big = 1
                    ratio = 3.0
                # 逆パターン（右が画像・左がテキスト）
                if has_img[1] and not has_text[1] and has_text[0] and weights[1] <= 360:
                    big = 0
                    ratio = 3.0
                if ratio >= threshold:
                    # add __span-2/3 to larger child depending on strength
                    cm = child_re.match(lines[child_idxs[big]])
                    if cm:
                        cls = cm.group(3)
                        span_tok = '__span-3' if ratio >= 2.5 else '__span-2'
                        # drop any previous __span-* then add the decided one
                        base = re.sub(r"\s+__span-[23]\b", "", cls)
                        if span_tok not in (' ' + base + ' '):
                            new_cls = base + ' ' + span_tok
                        else:
                            new_cls = base
                        if new_cls != cls:
                            lines[child_idxs[big]] = lines[child_idxs[big]].replace(cls, new_cls, 1)
                            changed = True
        i = j if j > i else i + 1
    if changed:
        out = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + '.span.bak').write_text(original, encoding='utf-8')
        html_path.write_text(out, encoding='utf-8')
    return changed


def main():
    ap = argparse.ArgumentParser(description='Detect non-equal spans under eq-cols rows and annotate __span-2 on larger column based on image widths or content weight')
    ap.add_argument('--root', required=True)
    ap.add_argument('--threshold', type=float, default=1.3)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    any_changed = False
    for hp in root.rglob('*.html'):
        if detect_spans_in_file(hp, root, threshold=args.threshold, backup=args.backup):
            any_changed = True
    print(f"[SPAN-DETECT] changed={any_changed}")


if __name__ == '__main__':
    main()
