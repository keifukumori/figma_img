#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path


GENERIC_TOKENS = {'section', 'c-section', 'content-width-container'}


def assign_keys_in_file(html_path: Path, prefix: str = 'section-', width: int = 2, backup: bool = False) -> int:
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    # Find <section ... class="..."> and ensure it has a unique section-* key
    idx = 0
    out = []
    last = 0
    changed = 0
    sec_re = re.compile(r"<section([^>]*)class=\"([^\"]+)\"([^>]*)>", re.I)
    for m in sec_re.finditer(text):
        before = text[last:m.start()]
        attrs1 = m.group(1)
        classes = m.group(2)
        attrs2 = m.group(3)
        toks = [c for c in classes.split() if c]
        has_key = any(t.startswith(prefix) for t in toks)
        if not has_key:
            # decide if current tokens are generic only
            non_generic = [t for t in toks if t not in GENERIC_TOKENS]
            if not non_generic:
                idx += 1
                key = f"{prefix}{str(idx).zfill(width)}"
                toks.append(key)
                new_classes = ' '.join(toks)
                repl = f"<section{attrs1}class=\"{new_classes}\"{attrs2}>"
                out.append(before)
                out.append(repl)
                last = m.end()
                changed += 1
            else:
                # Already has a meaningful token; leave as is
                continue
        else:
            continue
    out.append(text[last:])
    if changed:
        if backup:
            bak = html_path.with_suffix(html_path.suffix + '.sectkeys.bak')
            if not bak.exists():
                bak.write_text(original, encoding='utf-8')
        html_path.write_text(''.join(out), encoding='utf-8')
    return changed


def main():
    ap = argparse.ArgumentParser(description='Assign fallback section keys (section-01, section-02, ...) to <section> without meaningful class tokens')
    ap.add_argument('--root', required=True)
    ap.add_argument('--prefix', default='section-')
    ap.add_argument('--width', type=int, default=2)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()

    root = Path(args.root)
    changed_total = 0
    for hp in root.rglob('*.html'):
        try:
            changed_total += assign_keys_in_file(hp, prefix=args.prefix, width=args.width, backup=args.backup)
        except Exception:
            continue
    print(f"[SECT-KEYS] files_changed={changed_total}")


if __name__ == '__main__':
    main()

