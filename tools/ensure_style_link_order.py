#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


def ensure_order_in_file(html_path: Path, backup: bool = False) -> bool:
    try:
        text = html_path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False

    orig = text
    head_re = re.compile(r"<head[^>]*>", re.I)
    link_re = re.compile(r"<link[^>]+rel=\"stylesheet\"[^>]+href=\"([^\"]+)\"[^>]*>", re.I)

    # collect all stylesheet links in order
    links = []  # (start, end, href)
    for m in link_re.finditer(text):
        href = m.group(1)
        links.append((m.start(), m.end(), href))

    def find_link(href_name: str):
        for idx, (s, e, href) in enumerate(links):
            if href.endswith(href_name):
                return idx, (s, e, href)
        return None, None

    idx_style, style_link = find_link('style.css')
    idx_common, common_link = find_link('style-common.css')

    changed = False
    if style_link and common_link:
        # If common exists and appears before style.css, reorder to after
        if idx_common is not None and idx_style is not None and idx_common < idx_style:
            s1, e1, _ = common_link
            # remove common
            text = text[:s1] + text[e1:]
            # recompute style link position after removal
            # naive approach: search again for style.css
            m_style = re.search(r"<link[^>]+href=\"[^\"]*style\.css\"[^>]*>", text, re.I)
            if m_style:
                insert_pos = m_style.end()
                text = text[:insert_pos] + "\n    " + orig[s1:e1] + text[insert_pos:]
                changed = True
    elif style_link and not common_link:
        # Insert common after style.css if head exists
        m_head = head_re.search(text)
        if m_head:
            m_style = re.search(r"<link[^>]+href=\"[^\"]*style\.css\"[^>]*>", text, re.I)
            if m_style:
                insert_pos = m_style.end()
                snippet = '\n    <link rel="stylesheet" href="style-common.css">'
                text = text[:insert_pos] + snippet + text[insert_pos:]
                changed = True
    else:
        # No style.css found; ensure single common link in head if missing
        if 'style-common.css' not in text:
            m_head = head_re.search(text)
            if m_head:
                insert_pos = m_head.end()
                snippet = '\n    <link rel="stylesheet" href="style-common.css">'
                text = text[:insert_pos] + snippet + text[insert_pos:]
                changed = True

    if changed and text != orig:
        if backup:
            html_path.with_suffix(html_path.suffix + '.style_order.bak').write_text(orig, encoding='utf-8')
        html_path.write_text(text, encoding='utf-8')
    return changed


def main():
    ap = argparse.ArgumentParser(description='Ensure style-common.css is linked after style.css in HTML files')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    files = 0
    for hp in root.rglob('*.html'):
        try:
            if ensure_order_in_file(hp, backup=args.backup):
                files += 1
        except Exception:
            continue
    print(f"[STYLE-ORDER] files_changed={files}")


if __name__ == '__main__':
    main()

