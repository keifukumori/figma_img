#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


def find_project_json(root: Path) -> Path | None:
    # Try to locate a raw Figma JSON matching the project name under figma_images/raw_figma_data
    proj = root.name
    raw = root.parent / 'raw_figma_data'
    if raw.exists():
        # Prefer PC json (without _sp)
        cands = sorted([p for p in raw.glob(f"{proj}*.json")], key=lambda p: ("_sp.json" in p.name, p.stat().st_size))
        if cands:
            # pick non-sp first if present
            for p in cands:
                if '_sp.json' not in p.name:
                    return p
            return cands[0]
    return None


def build_id_index(json_path: Path, limit: int | None = None) -> dict[str, dict[str, float | str]]:
    """Build a minimal id -> {width, grow, sizing} index by line-scanning the large JSON.
    This is a tolerant regex-based scan to avoid loading the full JSON into memory.
    """
    id_map: dict[str, dict[str, float | str]] = {}
    cur_id: str | None = None
    in_abb = False
    abb_brace = 0
    width_val: float | None = None
    grow_val: float | None = None
    sizing_val: str | None = None
    id_re = re.compile(r'\"id\"\s*:\s*\"([0-9]+:[0-9]+)\"')
    width_re = re.compile(r'\"width\"\s*:\s*([0-9]+(?:\.[0-9]+)?)')
    grow_re = re.compile(r'\"layoutGrow\"\s*:\s*([0-9]+(?:\.[0-9]+)?)')
    sizing_re = re.compile(r'\"layoutSizingHorizontal\"\s*:\s*\"([A-Z]+)\"')
    with json_path.open('r', encoding='utf-8', errors='ignore') as f:
        for i, line in enumerate(f, 1):
            m = id_re.search(line)
            if m:
                # flush previous record if we had width or grow
                if cur_id and (width_val is not None or grow_val is not None or sizing_val is not None):
                    rec = id_map.setdefault(cur_id, {})
                    if width_val is not None:
                        rec['width'] = width_val
                    if grow_val is not None:
                        rec['grow'] = grow_val
                    if sizing_val is not None:
                        rec['sizing'] = sizing_val
                cur_id = m.group(1)
                width_val = None
                grow_val = None
                sizing_val = None
                in_abb = False
                abb_brace = 0
            if '"absoluteBoundingBox"' in line:
                in_abb = True
                abb_brace = 0
            if in_abb:
                abb_brace += line.count('{')
                abb_brace -= line.count('}')
                wm = width_re.search(line)
                if wm:
                    try:
                        width_val = float(wm.group(1))
                    except Exception:
                        pass
                if abb_brace <= 0:
                    in_abb = False
            gm = grow_re.search(line)
            if gm:
                try:
                    grow_val = float(gm.group(1))
                except Exception:
                    pass
            sm = sizing_re.search(line)
            if sm:
                sizing_val = sm.group(1)
            if limit and i >= limit:
                break
    # flush last
    if cur_id and (width_val is not None or grow_val is not None or sizing_val is not None):
        rec = id_map.setdefault(cur_id, {})
        if width_val is not None:
            rec['width'] = width_val
        if grow_val is not None:
            rec['grow'] = grow_val
        if sizing_val is not None:
            rec['sizing'] = sizing_val
    return id_map


def first_id_from_segment(seg: str) -> str | None:
    # Prefer image src id
    m = re.search(r'images/([0-9]+:[0-9]+)\.png', seg)
    if m:
        return m.group(1)
    # fallback: n-<id>
    m = re.search(r'\bn-([0-9]+-[0-9]+)\b', seg)
    if m:
        return m.group(1).replace('-', ':')
    return None


def annotate_spans_with_json(root: Path, idx: dict[str, dict[str, float | str]], threshold: float = 1.25, backup: bool = False) -> int:
    tag_open = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    child_open = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    files_changed = 0
    for hp in root.rglob('*.html'):
        lines = hp.read_text(encoding='utf-8', errors='ignore').splitlines()
        original = '\n'.join(lines) + '\n'
        changed = False
        i = 0
        while i < len(lines):
            m = tag_open.match(lines[i])
            if not m:
                i += 1
                continue
            indent = m.group(1)
            close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
            child_idxs = []
            j = i + 1
            while j < len(lines) and not close_re.match(lines[j]):
                cm = child_open.match(lines[j])
                if cm and cm.group(1) == indent + '  ':
                    child_idxs.append(j)
                j += 1
            if len(child_idxs) == 2:
                s0 = '\n'.join(lines[child_idxs[0]: child_idxs[1]])
                s1 = '\n'.join(lines[child_idxs[1]: j])
                id0 = first_id_from_segment(s0)
                id1 = first_id_from_segment(s1)
                w0 = idx.get(id0, {}).get('width') if id0 else None
                w1 = idx.get(id1, {}).get('width') if id1 else None
                # fallback to grow when width missing
                if not w0:
                    g0 = idx.get(id0, {}).get('grow') if id0 else None
                    if isinstance(g0, float) and g0 > 0:
                        w0 = 100.0 * g0
                if not w1:
                    g1 = idx.get(id1, {}).get('grow') if id1 else None
                    if isinstance(g1, float) and g1 > 0:
                        w1 = 100.0 * g1
                # fallback: if one side missing, approximate by text length without tags
                if w0 is None:
                    w0 = float(len(re.sub(r"<[^>]+>", "", s0)))
                if w1 is None:
                    w1 = float(len(re.sub(r"<[^>]+>", "", s1)))
                if isinstance(w0, float) and isinstance(w1, float) and min(w0, w1) > 0:
                    big = 0 if w0 >= w1 else 1
                    ratio = max(w0, w1) / min(w0, w1)
                    if ratio >= threshold:
                        # add __span-2/3 to bigger child
                        span_tok = '__span-3' if ratio >= 2.4 else '__span-2'
                        idx_big = child_idxs[big]
                        cm = child_open.match(lines[idx_big])
                        if cm:
                            cls = cm.group(3)
                            base = re.sub(r"\s+__span-[23]\b", "", cls)
                            if span_tok not in (' ' + base + ' '):
                                new_cls = base + ' ' + span_tok
                            else:
                                new_cls = base
                            if new_cls != cls:
                                lines[idx_big] = lines[idx_big].replace(cls, new_cls, 1)
                                changed = True
            i = j if j > i else i + 1
        out = '\n'.join(lines) + '\n'
        if changed and out != original:
            if backup:
                hp.with_suffix(hp.suffix + '.spanjson.bak').write_text(original, encoding='utf-8')
            hp.write_text(out, encoding='utf-8')
            files_changed += 1
    return files_changed


def main():
    ap = argparse.ArgumentParser(description='Annotate __span-2/3 for eq-cols 2-col rows using raw Figma JSON widths/grow')
    ap.add_argument('--root', required=True)
    ap.add_argument('--json', help='Path to raw Figma JSON (auto-detect if omitted)')
    ap.add_argument('--backup', action='store_true')
    ap.add_argument('--threshold', type=float, default=1.25)
    args = ap.parse_args()

    root = Path(args.root)
    json_path = Path(args.json) if args.json else find_project_json(root)
    if not json_path or not json_path.exists():
        print('[SPAN-JSON] json not found; skip')
        return
    idx = build_id_index(json_path)
    changed = annotate_spans_with_json(root, idx, threshold=args.threshold, backup=args.backup)
    print(f"[SPAN-JSON] files_changed={changed}")


if __name__ == '__main__':
    main()
