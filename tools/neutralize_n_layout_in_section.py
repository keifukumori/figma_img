#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


LAYOUT_PROPS = (
    'display', 'flex-direction', 'gap', 'justify-content', 'align-items', 'flex-wrap',
    'min-width', 'max-width', 'min-height', 'max-height', 'width', 'height',
)


def collect_section_n_tokens(html_path: Path, section_key: str) -> set[str]:
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    # Find section blocks with class starting with section_key (e.g., about)
    # Greedy but safe: split by <section ...> ... </section>
    tokens: set[str] = set()
    sec_re = re.compile(rf"<section[^>]*class=\"([^\"]*\b{re.escape(section_key)}\b[^\"]*)\"[^>]*>(.*?)</section>", re.I|re.S)
    for m in sec_re.finditer(text):
        body = m.group(2)
        for cm in re.finditer(r'class=\"([^\"]+)\"', body):
            for c in cm.group(1).split():
                if c.startswith('n-'):
                    tokens.add(c)
    return tokens


def neutralize_layout_in_css(css_path: Path, n_tokens: set[str], backup: bool) -> int:
    css = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    if not css:
        return 0
    original = css
    # For each n-token, find blocks that include it in selectors and comment out layout props
    def fix_block(m: re.Match) -> str:
        sels = m.group(1)
        body = m.group(2)
        # Only process if any of the selectors includes one of our n-tokens
        if not any((f'.{t}' in sels) for t in n_tokens):
            return m.group(0)
        out_lines = []
        changed_local = False
        for line in body.split(';'):
            if ':' not in line:
                continue
            k, v = line.split(':', 1)
            prop = k.strip().lower()
            if prop in LAYOUT_PROPS:
                out_lines.append(f'/* neutralized:{prop}:{v.strip()} */')
                changed_local = True
            else:
                out_lines.append(f'{prop}:{v.strip()}')
        new_body = (';\n    '.join(l for l in out_lines if l)) + (';' if out_lines else '')
        return f"{sels}{{\n    {new_body}\n}}"

    css2 = re.sub(r"([^{}]+)\{([^}]*)\}", fix_block, css, flags=re.S)
    if css2 != original:
        if backup:
            bak = css_path.with_suffix(css_path.suffix + '.neutralize_n.bak')
            if not bak.exists():
                bak.write_text(original, encoding='utf-8')
        css_path.write_text(css2, encoding='utf-8')
    return 1 if css2 != original else 0


def main():
    ap = argparse.ArgumentParser(description='Neutralize layout props in .n-* CSS for a target section (keeps visuals)')
    ap.add_argument('--root', required=True)
    ap.add_argument('--section', required=True, help='Section key (e.g., about)')
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    html = root / 'index.html'
    css = root / 'style.css'
    if not html.exists() or not css.exists():
        raise SystemExit('index.html or style.css not found under root')

    n_tokens = collect_section_n_tokens(html, args.section)
    if not n_tokens:
        print('[NEUTRALIZE-N] no n-* tokens found in section')
        return
    changed = neutralize_layout_in_css(css, n_tokens, backup=args.backup)
    print(f'[NEUTRALIZE-N] section={args.section} tokens={len(n_tokens)} css_changed={changed}')


if __name__ == '__main__':
    main()

