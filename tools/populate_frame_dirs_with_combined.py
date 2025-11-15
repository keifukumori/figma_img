#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path


def populate(root: Path, backup: bool = False) -> int:
    combined_index = root / 'index.html'
    css1 = root / 'style.css'
    css_common = root / 'style-common.css'
    images_dir = root / 'images'
    if not combined_index.exists() or not css1.exists():
        raise SystemExit(f'combined index/style.css not found under {root}')
    html = combined_index.read_text(encoding='utf-8', errors='ignore')

    changed = 0
    for sub in sorted(root.iterdir()):
        if not sub.is_dir():
            continue
        # per-frame folders typically have "*-pc.html"; use index-pc.html as target if present
        target = sub / 'index-pc.html'
        if not target.exists():
            continue
        # write combined html into per-frame index
        try:
            orig = target.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            orig = ''
        if html != orig:
            if backup:
                bak = target.with_suffix(target.suffix + '.popframe.bak')
                if not bak.exists():
                    bak.write_text(orig, encoding='utf-8')
            target.write_text(html, encoding='utf-8')
            changed += 1
        # ensure CSS files present
        for css_src in (css1, css_common):
            if css_src.exists():
                dst = sub / css_src.name
                if not dst.exists() or dst.read_text(encoding='utf-8', errors='ignore') != css_src.read_text(encoding='utf-8', errors='ignore'):
                    shutil.copy2(css_src, dst)
        # copy images (shallow)
        if images_dir.exists():
            dst_images = sub / 'images'
            dst_images.mkdir(exist_ok=True)
            for name in os.listdir(images_dir):
                s = images_dir / name
                d = dst_images / name
                if s.is_file():
                    if not d.exists() or s.stat().st_mtime > d.stat().st_mtime:
                        shutil.copy2(s, d)
    return changed


def main():
    ap = argparse.ArgumentParser(description='Populate per-frame folders (index-pc.html) with combined page content and assets')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    args = ap.parse_args()
    root = Path(args.root)
    ch = populate(root, backup=args.backup)
    print(f'[POP-FRAME] frames_updated={ch}')


if __name__ == '__main__':
    main()

