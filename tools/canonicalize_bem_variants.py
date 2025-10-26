#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Dict, List, Tuple


def parse_css_classes(css_text: str) -> Dict[str, Dict[str, str]]:
    cmap: Dict[str, Dict[str, str]] = {}
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css_text):
        sels = m.group(1)
        body = m.group(2)
        decls: Dict[str, str] = {}
        for part in body.split(';'):
            if ':' not in part:
                continue
            k, v = part.split(':', 1)
            k = k.strip().lower(); v = re.sub(r"\s+", ' ', v.strip().lower())
            if not k:
                continue
            decls[k] = v
        if not decls:
            continue
        for cls in re.findall(r"\.([a-zA-Z0-9_-]+)", sels):
            d = cmap.setdefault(cls, {})
            d.update(decls)
    return cmap


VAR_RE = re.compile(r"^([a-z0-9][a-z0-9_-]*__[a-z0-9][a-z0-9_-]*)__\d+$")


def quantize_px(v: str, step: int = 4) -> str:
    m = re.search(r"(-?\d+)", v or '')
    if not m:
        return v
    try:
        n = int(m.group(1))
        q = int(round(n / step) * step)
        return f"{q}px"
    except Exception:
        return v


WHITELIST = {
    'display','flex-direction','gap','justify-content','align-items','flex-wrap',
    'padding','padding-top','padding-right','padding-bottom','padding-left',
    'align-self','overflow'
}


def norm_props(kv: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in kv.items():
        if k not in WHITELIST:
            continue
        if k in ('gap','padding','padding-top','padding-right','padding-bottom','padding-left'):
            v = quantize_px(v)
        out[k] = v
    return out


def props_equal(a: Dict[str, str], b: Dict[str, str]) -> bool:
    return norm_props(a) == norm_props(b)


def intersection_props(dicts: List[Dict[str, str]]) -> Dict[str, str]:
    if not dicts:
        return {}
    keys = set(dicts[0].keys())
    for d in dicts[1:]:
        keys &= set(d.keys())
    out: Dict[str, str] = {}
    for k in sorted(keys):
        v0 = dicts[0].get(k)
        if all(dicts[i].get(k) == v0 for i in range(1, len(dicts))):
            out[k] = v0
    return {k: v for k, v in norm_props(out).items()}


def canonicalize(root: Path, backup: bool = False, force_bases: set[str] | None = None) -> Tuple[int, int]:
    css_path = root / 'style.css'
    css_text = css_path.read_text(encoding='utf-8', errors='ignore') if css_path.exists() else ''
    css_map = parse_css_classes(css_text)

    # Collect variant groups from CSS selectors first
    groups: Dict[str, List[str]] = {}
    for cls in css_map.keys():
        vm = VAR_RE.match(cls)
        if vm:
            base = vm.group(1)
            groups.setdefault(base, []).append(cls)

    # Also include variants that appear only in HTML (no CSS rule) and collect utility tokens per variant
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*?)>", re.I)
    class_re = re.compile(r'class=\"([^\"]+)\"')
    util_prefixes = ("fx-","g-","ai-","jc-","fw-","px-","py-","pt-","pr-","pb-","pl-","w-","h-","as-","clip","card")
    occ_tokens: Dict[str, List[Tuple[str,...]]] = {}
    for hp in root.rglob('*.html'):
        text = hp.read_text(encoding='utf-8', errors='ignore')
        for m in tag_re.finditer(text):
            cm = class_re.search(m.group(2))
            if not cm:
                continue
            classes = cm.group(1).split()
            toks = tuple(sorted([c for c in classes if any(c.startswith(p) for p in util_prefixes)]))
            for c in classes:
                vm = VAR_RE.match(c)
                if vm:
                    base = vm.group(1)
                    lst = groups.setdefault(base, [])
                    if c not in lst:
                        lst.append(c)
                    occ_tokens.setdefault(c, []).append(toks)

    # Decide which groups can be unified: CSS rules equal across variants, or no CSS rules at all
    unify_bases: Dict[str, Dict[str, str]] = {}
    for base, variants in groups.items():
        if len(variants) < 2:
            continue
        props_list = [css_map.get(v) or {} for v in variants]
        if force_bases and base in force_bases:
            # Force unify: use intersection of whitelisted props if any, else rely on utilities
            inter = intersection_props(props_list) if any(p for p in props_list) else {}
            unify_bases[base] = inter
            continue
        decided = False
        # If all empty -> safe to unify (rely on utilities)
        if all(not p for p in props_list):
            unify_bases[base] = {}
            decided = True
        # All equal after normalization?
        if not decided:
            eq = True
            for i in range(1, len(props_list)):
                if not props_equal(props_list[0], props_list[i]):
                    eq = False
                    break
            if eq:
                inter = intersection_props(props_list)
                unify_bases[base] = inter
                decided = True
        # Otherwise, check HTML token equality across variants
        if not decided:
            token_sets = set()
            ok = True
            for v in variants:
                occ = occ_tokens.get(v) or []
                if not occ:
                    ok = False; break
                # use the first occurrence as representative
                token_sets.add(occ[0])
            if ok and len(token_sets) == 1:
                unify_bases[base] = {}
                decided = True
        # Fallback: compare raw CSS bodies for exact equality
        if not decided and css_text:
            bodies = []
            for v in variants:
                m = re.search(rf"\.{re.escape(v)}\s*\{{([^}}]*)\}}", css_text)
                bodies.append(re.sub(r"\s+", " ", m.group(1).strip()) if m else "")
            if bodies and all(b == bodies[0] for b in bodies):
                # Normalize whitelisted subset only
                inter = intersection_props(props_list)
                unify_bases[base] = inter

    if not unify_bases:
        return (0, 0)

    # Write CSS: add base rules for intersection
    if backup:
        bak = css_path.with_suffix(css_path.suffix + '.bemcanon.bak')
        if css_text and not bak.exists():
            bak.write_text(css_text, encoding='utf-8')
    css_append = []
    for base, inter in unify_bases.items():
        if not inter:
            # no extra CSS needed
            continue
        body = '; '.join(f"{k}: {v}" for k, v in sorted(inter.items()))
        rule = f"\n/* canonicalized BEM base */\n.{base} {{ {body}; }}\n"
        if rule not in css_text:
            css_append.append(rule)
    if css_append:
        with css_path.open('a', encoding='utf-8') as f:
            for r in css_append:
                f.write(r)

    # Rewrite HTML classes: replace variants with base
    files_changed = 0
    replacements = 0
    for hp in root.rglob('*.html'):
        text = hp.read_text(encoding='utf-8', errors='ignore')
        orig = text
        def repl(m: re.Match) -> str:
            before, classes, after = m.group(1), m.group(2), m.group(3)
            arr = classes.split()
            changed = False
            for i, c in enumerate(list(arr)):
                vm = VAR_RE.match(c)
                if vm:
                    base = vm.group(1)
                    if base in unify_bases:
                        arr[i] = base
                        changed = True
            if not changed:
                return m.group(0)
            nonlocal replacements
            replacements += 1
            return before + ' '.join(arr) + after
        text = re.sub(r'(class=\")([^\"]+)(\")', repl, text)
        if text != orig:
            if backup:
                hp.with_suffix(hp.suffix + '.bemcanon.bak').write_text(orig, encoding='utf-8')
            hp.write_text(text, encoding='utf-8')
            files_changed += 1
    return (files_changed, replacements)


def main():
    ap = argparse.ArgumentParser(description='Canonicalize BEM variants like about__h2__7 -> about__h2 when CSS is equal or absent')
    ap.add_argument('--root', required=True)
    ap.add_argument('--backup', action='store_true')
    ap.add_argument('--force-base', help='Comma-separated base BEMs to force unify (e.g., about__h2,about__h3)')
    args = ap.parse_args()

    root = Path(args.root)
    force_bases: set[str] | None = None
    if args.force_base:
        force_bases = {b.strip() for b in args.force_base.split(',') if b.strip()}
    files_changed, replacements = canonicalize(root, backup=args.backup, force_bases=force_bases)
    print(f"[BEM-CANON] files_changed={files_changed}, class_attrs_modified={replacements}")


if __name__ == '__main__':
    main()
