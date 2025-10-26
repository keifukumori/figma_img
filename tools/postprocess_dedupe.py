#!/usr/bin/env python3
import argparse
import json
import os
import re
import subprocess
from pathlib import Path


FLEX_PROPS = [
    "display",
    "flex-direction",
    "justify-content",
    "align-items",
    "gap",
    "flex-wrap",
    # padding (shorthand and sides) for utility extraction
    "padding",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
    # limited width/height signals for safe utilities
    "width",
    "height",
    # self-alignment for child items
    "align-self",
]


def parse_args():
    p = argparse.ArgumentParser(description="Post-process generated HTML/CSS to add reusable flex utilities safely.")
    p.add_argument("--root", required=True, help="Root directory containing generated HTML/CSS (e.g., figma_images/Project)")
    p.add_argument("--min-occurs", type=int, default=3, help="Minimum occurrences for a pattern to be considered common")
    p.add_argument("--props", default=",".join(FLEX_PROPS), help="Comma-separated list of props to consider")
    p.add_argument("--dry-run", action="store_true", help="Do not modify files; only write style-buckets.json")
    p.add_argument("--inject-css", action="store_true", help="Write style-common.css and inject <link> + add utility classes to HTML")
    p.add_argument("--backup", action="store_true", help="Write .bak backups when modifying files")
    p.add_argument("--comment-out-covered", action="store_true", help="Conservatively comment out covered flex declarations in style.css")
    p.add_argument("--promote-visuals", action="store_true", help="Opt-in: promote identical visuals (background/shadow/radius) into .row-item")
    p.add_argument("--consolidate-non-eq", action="store_true", help="Opt-in: consolidate common tokens across non-equalized fx-row siblings")
    # Sectionize options (safe mode)
    p.add_argument("--sectionize", action="store_true", help="Wrap eligible blocks in <section> safely (wrapper mode)")
    p.add_argument("--require-heading", action="store_true", default=True, help="Require at least one h1–h6 inside block (default: true)")
    p.add_argument("--min-children", type=int, default=2, help="Require at least this many child opening tags inside (default: 2)")
    p.add_argument("--exclude-roles", default="header,footer,nav", help="Comma-separated name fragments to exclude (default: header,footer,nav)")
    return p.parse_args()


def find_html_files(root: Path):
    return [*root.glob("**/*.html")]


def extract_kv(style_text: str):
    kv = {}
    for part in style_text.split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            k = k.strip().lower()
            v = re.sub(r"\s+", " ", v.strip().lower())
            if k:
                kv[k] = v
    return kv


def infer_props_from_classes(class_str: str):
    props = {}
    classes = class_str.split()
    if "layout-flex-row" in classes:
        props["display"] = "flex"
        props["flex-direction"] = "row"
    if "layout-flex-col" in classes:
        props["display"] = "flex"
        props["flex-direction"] = "column"
    return props


def normalize_value(prop: str, val: str):
    if prop == "gap":
        m = re.search(r"(-?\d+)", val)
        if m:
            return f"{int(m.group(1))}px"
    return val


def normalize_props(props: dict, prop_list):
    out = {}
    for p in prop_list:
        if p in props:
            out[p] = normalize_value(p, props[p])
    return out


def pattern_key(props: dict):
    items = sorted(props.items())
    return json.dumps(items, ensure_ascii=False)


def util_classes_for(props: dict):
    classes = []
    if props.get("display") == "flex":
        if props.get("flex-direction") == "row":
            classes.append("fx-row")
        elif props.get("flex-direction") == "column":
            classes.append("fx-col")
    if "gap" in props:
        g = re.search(r"(-?\d+)", props["gap"])
        if g:
            classes.append(f"g-{int(g.group(1))}")
    ai = props.get("align-items")
    if ai:
        token = ai.replace(" ", "-")
        classes.append(f"ai-{token}")
    jc = props.get("justify-content")
    if jc:
        token = jc.replace(" ", "-")
        classes.append(f"jc-{token}")
    fw = props.get("flex-wrap")
    if fw:
        token = fw.replace(" ", "-")
        classes.append(f"fw-{token}")
    # align-self
    als = props.get("align-self")
    if als:
        token = als.replace(" ", "-")
        classes.append(f"as-{token}")
    # width/height limited utilities
    w = (props.get("width") or "").strip().lower()
    if w in ("auto", "100%"):
        classes.append("w-auto" if w == "auto" else "w-full")
    h = (props.get("height") or "").strip().lower()
    if h in ("auto", "100%"):
        classes.append("h-auto" if h == "auto" else "h-full")
    # min-width/min-height zero utilities
    mw = (props.get("min-width") or "").strip().lower()
    if mw in ("0", "0px"):
        classes.append("min-w-0")
    mh = (props.get("min-height") or "").strip().lower()
    if mh in ("0", "0px"):
        classes.append("min-h-0")
    # padding shorthand -> pt-/pr-/pb-/pl- (integers only)
    def _num(s: str) -> int | None:
        m = re.search(r"(-?\d+)", s or "")
        return int(m.group(1)) if m else None
    paddings = {k: None for k in ("top", "right", "bottom", "left")}
    if "padding" in props:
        val = props["padding"].strip()
        parts = re.split(r"\s+", val)
        nums = [_num(p) for p in parts if _num(p) is not None]
        if len(nums) == 1:
            paddings = dict.fromkeys(paddings, nums[0])
        elif len(nums) == 2:
            paddings["top"] = paddings["bottom"] = nums[0]
            paddings["left"] = paddings["right"] = nums[1]
        elif len(nums) == 3:
            paddings["top"] = nums[0]; paddings["left"] = paddings["right"] = nums[1]; paddings["bottom"] = nums[2]
        elif len(nums) >= 4:
            paddings["top"], paddings["right"], paddings["bottom"], paddings["left"] = nums[:4]
    # override by side-specific if present
    if "padding-top" in props:
        paddings["top"] = _num(props["padding-top"]) or paddings.get("top")
    if "padding-right" in props:
        paddings["right"] = _num(props["padding-right"]) or paddings.get("right")
    if "padding-bottom" in props:
        paddings["bottom"] = _num(props["padding-bottom"]) or paddings.get("bottom")
    if "padding-left" in props:
        paddings["left"] = _num(props["padding-left"]) or paddings.get("left")
    # add tokens
    try:
        t, r, b, l = paddings["top"], paddings["right"], paddings["bottom"], paddings["left"]
        if t is not None and b is not None and t == b and t > 0:
            classes.append(f"py-{t}")
        else:
            if t and t > 0:
                classes.append(f"pt-{t}")
            if b and b > 0:
                classes.append(f"pb-{b}")
        if l is not None and r is not None and l == r and l > 0:
            classes.append(f"px-{l}")
        else:
            if l and l > 0:
                classes.append(f"pl-{l}")
            if r and r > 0:
                classes.append(f"pr-{r}")
    except Exception:
        pass
    return classes


def scan_html(html_path: Path, prop_list):
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    instances = []
    # regex for tags with class and optional style
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*?)>", re.I)
    class_re = re.compile(r"class=\"([^\"]+)\"")
    style_re = re.compile(r"style=\"([^\"]+)\"")
    for m in tag_re.finditer(text):
        attrs = m.group(2)
        cm = class_re.search(attrs)
        if not cm:
            continue
        classes = cm.group(1)
        sm = style_re.search(attrs)
        style_kv = extract_kv(sm.group(1)) if sm else {}
        props = {}
        props.update(infer_props_from_classes(classes))
        props.update(style_kv)
        nprops = normalize_props(props, prop_list)
        if not nprops:
            continue
        instances.append({
            "file": str(html_path.relative_to(html_path.parent.parent)) if html_path.parent.parent in html_path.parents else str(html_path),
            "classes": classes,
            "style": style_kv,
            "props": nprops,
            "match_span": [m.start(), m.end()],
        })
    return instances


def build_buckets(instances, min_occurs):
    buckets = {}
    for inst in instances:
        k = pattern_key(inst["props"])
        buckets.setdefault(k, {"props": inst["props"], "items": []})
        buckets[k]["items"].append(inst)
    # filter
    common = {k: v for k, v in buckets.items() if len(v["items"]) >= min_occurs}
    return common


def write_style_common(root: Path, needed_utils):
    # Build CSS with :where to keep specificity minimal
    lines = [
        "/* Auto-generated common flex utilities */",
        ":where(.fx-row){display:flex;flex-direction:row;}",
        ":where(.fx-col){display:flex;flex-direction:column;}",
    ]
    gaps = sorted({u for u in needed_utils if u.startswith("g-")}, key=lambda s: int(s.split("-", 1)[1]))
    for g in gaps:
        n = int(g.split("-", 1)[1])
        lines.append(f":where(.{g}){{gap:{n}px;}}")
    ai_set = {u for u in needed_utils if u.startswith("ai-")}
    for ai in sorted(ai_set):
        v = ai[3:]
        lines.append(f":where(.{ai}){{align-items:{v};}}")
    jc_set = {u for u in needed_utils if u.startswith("jc-")}
    for jc in sorted(jc_set):
        v = jc[3:]
        lines.append(f":where(.{jc}){{justify-content:{v};}}")
    fw_set = {u for u in needed_utils if u.startswith("fw-")}
    for fw in sorted(fw_set):
        v = fw[3:]
        lines.append(f":where(.{fw}){{flex-wrap:{v};}}")
    # align-self utilities
    as_set = {u for u in needed_utils if u.startswith("as-")}
    for a in sorted(as_set):
        v = a[3:].replace("-", " ")
        lines.append(f":where(.{a}){{align-self:{v};}}")
    # width/height simple utilities
    if 'w-full' in needed_utils:
        lines.append(":where(.w-full){width:100%;}")
    if 'w-auto' in needed_utils:
        lines.append(":where(.w-auto){width:auto;}")
    if 'h-full' in needed_utils:
        lines.append(":where(.h-full){height:100%;}")
    if 'h-auto' in needed_utils:
        lines.append(":where(.h-auto){height:auto;}")
    if 'min-w-0' in needed_utils:
        lines.append(":where(.min-w-0){min-width:0;}")
    if 'min-h-0' in needed_utils:
        lines.append(":where(.min-h-0){min-height:0;}")
    # flex helpers
    if 'flex-1' in needed_utils:
        lines.append(":where(.flex-1){flex:1 1 0;}")
    # basis-<px> helpers
    basis_tokens = sorted({u for u in needed_utils if u.startswith('basis-')}, key=lambda s: int(re.findall(r"\d+", s)[0]) if re.findall(r"\d+", s) else 0)
    for bt in basis_tokens:
        try:
            n = int(bt.split('-',1)[1])
            lines.append(f":where(.{bt}){{flex:0 0 {n}px; width:{n}px;}}")
        except Exception:
            continue
    # Equal columns trigger
    lines.append(":where(.eq-cols)>*{flex:1 1 0;min-width:0}")
    # Neutralize per-child heights inside equalized rows
    lines.append(":where(.eq-cols)>[class^=\"n-\"], :where(.eq-cols)>[class*=\" n-\"]{height:auto;min-height:0}")
    # Row-item modifiers (derived)
    lines.append(":where(.__center){justify-content:center}")
    lines.append(":where(.__end){justify-content:flex-end}")
    lines.append(":where(.__between){justify-content:space-between}")
    # Equalized column span modifiers (structure)
    lines.append(":where(.eq-cols)>*.__span-2{flex:2 1 0}")
    lines.append(":where(.eq-cols)>*.__span-3{flex:3 1 0}")
    # padding utilities
    def _emit_pad(prefix: str, css_prop: str):
        pad_set = sorted({u for u in needed_utils if u.startswith(prefix+"-")}, key=lambda s: int(s.split("-", 1)[1]))
        for token in pad_set:
            try:
                n = int(token.split("-", 1)[1])
                lines.append(f":where(.{token}){{{css_prop}:{n}px;}}")
            except Exception:
                continue
    # combined x/y first (lower specificity required)
    _emit_pad("px", "padding-left")
    _emit_pad("px", "padding-right")
    _emit_pad("py", "padding-top")
    _emit_pad("py", "padding-bottom")
    # side-specific
    _emit_pad("pt", "padding-top")
    _emit_pad("pr", "padding-right")
    _emit_pad("pb", "padding-bottom")
    _emit_pad("pl", "padding-left")
    # Overflow guard for images in two-column layouts (Windows subpixel/rounding differences)
    lines.append(":where(.layout-2col) img{max-width:100%;height:auto;display:block}")
    # Equalize cards in row contexts (safe default)
    lines.append(":where(.layout-2col, .layout-flex-row, .fx-row) > .card{flex:1 1 0;min-width:0}")
    # BEM-first: prefer role classes over positional
    lines.append(":where(.layout-2col__col--first) img{max-width:100%;width:auto;height:auto;display:block}")
    # Fallback for legacy role classes (to be removed later)
    lines.append(":where(.layout-2col) .col-first img{max-width:100%;width:auto;height:auto;display:block}")
    # Fullbleed background alignment via CSS variables (focal and offsets)
    # Fullbleed background: center via margin calc to avoid transform drift/OS scrollbar width issues
    lines.append(":where(.bg-fullbleed){position:relative;width:100vw;max-width:100vw;margin-left:calc(50% - 50vw);margin-right:calc(50% - 50vw);background-repeat:no-repeat;background-size:cover;background-position: calc(var(--bg-x, 50%) + var(--bg-offset-x, 0px)) calc(var(--bg-y, 50%) + var(--bg-offset-y, 0px));}")
    # Helpers: class-based focal alignment
    lines.append(":where(.bg-align-left){--bg-x:0%;}")
    lines.append(":where(.bg-align-center){--bg-x:50%;}")
    lines.append(":where(.bg-align-right){--bg-x:100%;}")
    lines.append(":where(.bg-align-top){--bg-y:0%;}")
    lines.append(":where(.bg-align-middle){--bg-y:50%;}")
    lines.append(":where(.bg-align-bottom){--bg-y:100%;}")
    # Helpers: data-attribute based focal alignment
    lines.append('[data-bg-x="left"]{--bg-x:0%;}')
    lines.append('[data-bg-x="center"]{--bg-x:50%;}')
    lines.append('[data-bg-x="right"]{--bg-x:100%;}')
    lines.append('[data-bg-y="top"]{--bg-y:0%;}')
    lines.append('[data-bg-y="middle"]{--bg-y:50%;}')
    lines.append('[data-bg-y="bottom"]{--bg-y:100%;}')
    # Add responsive heuristics for SP under 768px (single DOM)
    sp: list[str] = []
    sp.append("@media (max-width: 768px) {")
    # Columnize rows and collapse multi-column layouts (no !important; rely on order + equal specificity)
    sp.append("  .fx-row{flex-direction:column; align-items:stretch;}")
    sp.append("  .fx-row > *{width:100%; min-width:0; flex:1 1 100%; margin-left:0; margin-right:0;}")
    sp.append("  .layout-2col, .layout-3col, .layout-4col{display:flex;flex-direction:column;}")
    sp.append("  .layout-2col > *, .layout-3col > *, .layout-4col > *{flex:1 1 100%; min-width:0; width:100%;}")
    # Fallback for generated d-flex blocks without tokens (e.g., about__d-flex_283)
    sp.append("  [class*='__d-flex_']{display:flex;flex-direction:column;}")
    sp.append("  [class*='__d-flex_'] > *{width:100%; min-width:0; flex:1 1 100%; margin-left:0; margin-right:0;}")
    # Ensure shadows are visible in collapsed rows: avoid clipping (no child side margins to keep alignment)
    sp.append("  .fx-row, .about__d-flex{overflow:visible;}")
    # Neutralize fixed widths at SP (common width tokens and wrappers)
    sp.append("  [class*='w__']{ width:auto; max-width:100%; min-width:0;}")
    sp.append("  .fixed-width, .rectangle, .img{ width:100%; max-width:100%; min-width:0;}")
    # Shrink large gaps conservatively (~60%)
    for g in gaps:
        try:
            n = int(g.split("-", 1)[1])
            shrink = max(4, int(round(n * 0.6)))
            sp.append(f"  :where(.{g}){{gap:{shrink}px}}")
        except Exception:
            continue
    # Clamp horizontal padding of content container
    sp.append("  .content-width-container{padding-left:clamp(12px,5vw,20px);padding-right:clamp(12px,5vw,20px);}")
    sp.append("}")

    out = root / "style-common.css"
    out.write_text("\n".join(lines + ["\n"] + sp) + "\n", encoding="utf-8")
    return out


# Tokens that our utilities know how to style even if they were not discovered from CSS props
UTIL_TOKEN_RE = re.compile(r"\b(?:fx-(?:row|col)|g-\d+|ai-(?:flex-start|center|flex-end)|jc-(?:flex-start|center|flex-end|space-between)|fw-(?:nowrap|wrap)|p[trblxy]-\d+|w-(?:auto|full)|h-(?:auto|full)|as-[a-z-]+|min-w-0|min-h-0|flex-1|basis-\d+)\b")


def collect_util_tokens_from_html(root: Path) -> set[str]:
    tokens: set[str] = set()
    for html_path in find_html_files(root):
        try:
            text = html_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in UTIL_TOKEN_RE.finditer(text):
            tokens.add(m.group(0))
    return tokens


def parse_css_class_props(css_path: Path, covered_props: set):
    if not css_path.exists():
        return {}
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    class_map = {}
    # naive parser for simple rules: .class { prop: val; ... }
    rule_re = re.compile(r"(\.[a-zA-Z0-9_-]+)\s*\{([^}]+)\}")
    for m in rule_re.finditer(css):
        sel = m.group(1)
        body = m.group(2)
        kv = extract_kv(body)
        nprops = {}
        for k, v in kv.items():
            if k in covered_props:
                nprops[k] = normalize_value(k, v)
        if nprops:
            class_map[sel] = nprops
    return class_map


def inject_link_and_classes(html_path: Path, class_prop_map: dict, covered_props: set, backup=False):
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    # inject link in head if not present
    if "style-common.css" not in text:
        # Insert link just after <head ...>, using a proper backreference (\1)
        text = re.sub(
            r"(<head[^>]*>)",
            r"\1\n    <link rel=\"stylesheet\" href=\"style-common.css\">",
            text,
            count=1,
            flags=re.I,
        )
    # add classes to matching tags by offset replacement
    # Build replacements in reverse order to keep offsets stable
    edits = []
    tag_re = re.compile(r"<(div|section|nav|ul|li|header|footer|article)([^>]*?)>", re.I)
    class_re = re.compile(r"class=\"([^\"]+)\"")
    for m in tag_re.finditer(text):
        attrs = m.group(2)
        cm = class_re.search(attrs)
        if not cm:
            continue
        cls = cm.group(1)
        key = (cls.strip(),)  # simple key – we don't track per-node; add where possible
        # decide utilities based on inline style in this tag
        style_m = re.search(r"style=\"([^\"]+)\"", attrs)
        style_kv = extract_kv(style_m.group(1)) if style_m else {}
        props = {}
        props.update(infer_props_from_classes(cls))
        # augment props from known class mappings in CSS (e.g., .n-xxxx, .layout-*, .frame-*)
        for one in cls.split():
            p = class_prop_map.get('.' + one)
            if p:
                # only take covered flex props to avoid noise
                for k, v in p.items():
                    if k in covered_props:
                        props[k] = v
        props.update(style_kv)
        nprops = normalize_props(props, FLEX_PROPS)
        utils = util_classes_for(nprops)
        # Do not inject padding tokens to keep HTML class concise; rely on base/alias CSS instead
        utils = [u for u in utils if not u.startswith(('px-','py-','pt-','pr-','pb-','pl-'))]
        if not utils:
            continue
        add = " ".join(u for u in utils if u not in cls.split())
        if not add:
            continue
        # replace class attribute
        new_cls = cls + " " + add
        new_attrs = attrs[:cm.start()] + f'class="{new_cls}"' + attrs[cm.end():]
        new_tag = f"<{m.group(1)}{new_attrs}>"
        edits.append((m.start(), m.end(), new_tag))
    if edits:
        edits.sort(reverse=True)
        for s, e, replacement in edits:
            text = text[:s] + replacement + text[e:]
    if text != original:
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(text, encoding="utf-8")


def add_two_col_role_classes(html_path: Path, backup=False):
    """Add .col-first / .col-second to direct children of .layout-2col containers.
    Heuristic based on first two child opening tags before the matching close at same indent.
    """
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\blayout-2col\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_re_tpl = r"^{indent}</div>\s*$"
    i = 0
    changed = False
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        first_idx = None
        second_idx = None
        j = i + 1
        while j < len(lines):
            if close_re.match(lines[j]):
                break
            cm = child_re.match(lines[j])
            if cm:
                # treat as a child opening tag (heuristic)
                if first_idx is None:
                    first_idx = j
                elif second_idx is None:
                    second_idx = j
                    break
            j += 1
        # add role classes if found
        def add_role(idx, role):
            nonlocal changed
            if idx is None:
                return
            m2 = child_re.match(lines[idx])
            if not m2:
                return
            cls = m2.group(3)
            classes = cls.split()
            if role in classes:
                return
            # add simple role
            classes.append(role)
            # add BEM roles for layout-2col
            if role == "col-first":
                if "layout-2col__col" not in classes:
                    classes.append("layout-2col__col")
                if "layout-2col__col--first" not in classes:
                    classes.append("layout-2col__col--first")
            elif role == "col-second":
                if "layout-2col__col" not in classes:
                    classes.append("layout-2col__col")
                if "layout-2col__col--second" not in classes:
                    classes.append("layout-2col__col--second")
            new_cls = " ".join(classes)
            # replace only class attribute inside the line
            lines[idx] = re.sub(r"class=\"[^\"]+\"", f'class="{new_cls}"', lines[idx], count=1)
            changed = True
        add_role(first_idx, "col-first")
        add_role(second_idx, "col-second")
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def sectionize_safe(html_path: Path, require_heading: bool, min_children: int, exclude_roles: set, backup=False):
    """Wrap eligible blocks in <section> with incremental ids (section-001...), non-destructive.
    Eligibility heuristics:
      - line with <div ... class="...frame..."> (or layout container)
      - contains at least one <h1>-<h6> if require_heading
      - contains at least min_children child opening tags
      - class name does not include any of exclude_roles fragments
      - avoids already wrapped sections
    """
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\bframe\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"[^\"]+\"[^>]*>")
    close_re_tpl = r"^{indent}</div>\s*$"
    section_count = 0
    i = 0
    changed = False
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        # exclude roles by class fragment
        if any(role.strip().lower() in classes.lower() for role in exclude_roles if role.strip()):
            i += 1
            continue
        # find matching close at same indent
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        has_heading = False
        child_count = 0
        j = i + 1
        while j < len(lines):
            if close_re.match(lines[j]):
                break
            if re.search(r"<h[1-6]\b", lines[j], re.I):
                has_heading = True
            if child_re.match(lines[j]):
                child_count += 1
            j += 1
        if j >= len(lines):
            i += 1
            continue
        # eligibility
        if require_heading and not has_heading:
            i = j + 1
            continue
        if child_count < min_children:
            i = j + 1
            continue
        # avoid double-wrapping: if previous non-empty is already <section> open at same indent
        prev = i - 1
        while prev >= 0 and not lines[prev].strip():
            prev -= 1
        if prev >= 0 and lines[prev].strip().startswith(f"{indent}<section"):
            i = j + 1
            continue
        # perform wrapping
        section_count += 1
        sec_id = f"section-{section_count:03d}"
        open_tag = f"{indent}<section id=\"{sec_id}\" class=\"c-section\">"
        close_tag = f"{indent}</section>"
        lines.insert(i, open_tag)
        # adjust j due to insertion
        j += 1
        lines.insert(j + 1, close_tag)
        changed = True
        i = j + 2
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def ensure_fullbleed_content_wrapper(html_path: Path, backup=False):
    """Ensure .bg-fullbleed has a direct .content-width-container wrapper for its content.
    If missing, insert it to center inner content.
    """
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\bbg-fullbleed\b[^\"]*)\"[^>]*>")
    cwc_re = re.compile(r"^\s*<div[^>]*\bclass=\"[^\"]*\bcontent-width-container\b[^\"]*\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    i = 0
    changed = False
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        # find first non-empty line after opening
        j = i + 1
        while j < len(lines) and not lines[j].strip():
            j += 1
        has_wrapper = j < len(lines) and cwc_re.match(lines[j]) is not None
        if not has_wrapper:
            # find matching close for bg-fullbleed
            close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
            k = j
            while k < len(lines) and not close_re.match(lines[k]):
                k += 1
            # insert wrapper after opening, and closing before bg-fullbleed close
            inner_indent = indent + "  "
            lines.insert(i + 1, f"{inner_indent}<div class=\"content-width-container\">")
            # adjust closing insertion index due to insertion
            k += 1
            lines.insert(k, f"{inner_indent}</div>")
            changed = True
            # move index past inserted block
            i = k + 1
        else:
            i = j + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def add_eq_cols_to_rows(html_path: Path, backup=False):
    """Detect fx-row parents with 2–4 direct children and add .eq-cols to parent.
    Also ensures .min-w-0 on those children to avoid overflow in equalized rows.
    Heuristics: count 2–4 direct child opening tags at the same indent; skip if any child has fixed width token (w__NNN).
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\bfx-row\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_re_tpl = r"^{indent}</div>\s*$"
    changed = False
    i = 0
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        child_idxs = []
        j = i + 1
        while j < len(lines):
            if close_re.match(lines[j]):
                break
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                child_idxs.append(j)
            j += 1
        if 2 <= len(child_idxs) <= 4:
            # quick ratio check for the 2-child case to avoid equalizing non-equal layouts
            if len(child_idxs) == 2:
                s0 = "\n".join(lines[child_idxs[0]: child_idxs[1]])
                s1 = "\n".join(lines[child_idxs[1]: j])
                # prefer image width if present; fallback to text length
                def _img_w(seg: str) -> int | None:
                    m2 = re.search(r'<img[^>]*\bsrc=\"([^\"]+)\"', seg)
                    if not m2:
                        return None
                    p = (html_path.parent / m2.group(1)).resolve()
                    try:
                        with open(p, 'rb') as f:
                            sig = f.read(8)
                            if sig != b"\x89PNG\r\n\x1a\n":
                                return None
                            _ = f.read(8)  # len + IHDR
                            data = f.read(13)
                            if len(data) == 13:
                                return int.from_bytes(data[0:4], 'big')
                    except Exception:
                        return None
                    return None
                w0 = _img_w(s0)
                w1 = _img_w(s1)
                if w0 is None:
                    w0 = len(re.sub(r"<[^>]+>", "", s0))
                if w1 is None:
                    w1 = len(re.sub(r"<[^>]+>", "", s1))
                if min(w0, w1) > 0:
                    ratio = max(w0, w1) / min(w0, w1)
                    if ratio >= 1.25:
                        # skip eq-cols to avoid forced equal widths; children will be annotated later
                        i = j if j > i else i + 1
                        continue
            # check no fixed width token on children
            no_fixed = True
            for idx in child_idxs:
                cm = child_re.match(lines[idx])
                if not cm:
                    continue
                cstr = cm.group(3)
                if re.search(r"\bw__\d+\b", cstr):
                    no_fixed = False
                    break
            if no_fixed and ' eq-cols ' not in (' '+classes+' '):
                new = classes + ' eq-cols'
                lines[i] = lines[i].replace(classes, new, 1)
                changed = True
            # ensure min-w-0 and min-h-0 on children (min-height neutralization + coverage tokens)
            for idx in child_idxs:
                cm = child_re.match(lines[idx])
                if not cm:
                    continue
                cstr = cm.group(3)
                new_cstr = cstr
                if ' min-w-0 ' not in (' '+new_cstr+' '):
                    new_cstr = new_cstr + ' min-w-0'
                if ' min-h-0 ' not in (' '+new_cstr+' '):
                    new_cstr = new_cstr + ' min-h-0'
                if new_cstr != cstr:
                    lines[idx] = lines[idx].replace(cstr, new_cstr, 1)
                    changed = True
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def normalize_eq_cols_rows(html_path: Path, backup=False):
    """For rows marked with .eq-cols, enforce ai-stretch on the parent and remove
    redundant child height/self-alignment tokens (h-full/h-auto/as-*) from direct children.
    This makes equal-height rows consistent without per-child hacks.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    class_re = re.compile(r'class=\"([^\"]+)\"')
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_re_tpl = r"^{indent}</div>\s*$"
    changed = False
    i = 0
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        # alignment normalization skipped to avoid adding property-like tokens
        cls_list = classes.split()
        # walk direct children until close
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                cstr = cm.group(3)
                toks = cstr.split()
                before = list(toks)
                # remove redundant height/self-alignment under eq-cols
                toks = [t for t in toks if t not in ('h-full','h-auto') and not t.startswith('as-')]
                if toks != before:
                    lines[j] = lines[j].replace(cstr, ' '.join(toks), 1)
                    changed = True
            j += 1
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def _extract_tokens(class_str: str) -> set[str]:
    toks = set()
    for c in class_str.split():
        if re.match(r"^(fx\-(?:row|col)|fw\-(?:nowrap|wrap)|g\-\d+|ai\-[a-z\-]+|jc\-[a-z\-]+|p[trblxy]\-\d+|w\-(?:auto|full)|h\-(?:auto|full)|min\-w\-0|min\-h\-0|flex\-1|basis\-\d+)$", c):
            toks.add(c)
    return toks


def _tokens_to_css(tokens: set[str]) -> list[str]:
    decls: list[str] = []
    for t in sorted(tokens):
        if t == 'fx-row':
            decls += ['display:flex', 'flex-direction:row']
        elif t == 'fx-col':
            decls += ['display:flex', 'flex-direction:column']
        elif t == 'flex-1':
            decls += ['flex:1 1 0']
        elif t.startswith('g-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'gap:{n}px')
            except Exception:
                pass
        elif t.startswith('basis-'):
            try:
                n = int(t.split('-',1)[1]); decls += [f'flex:0 0 {n}px', f'width:{n}px']
            except Exception:
                pass
        elif t.startswith('ai-'):
            decls.append(f'align-items:{t[3:]}')
        elif t.startswith('fw-'):
            decls.append(f'flex-wrap:{t[3:]}')
        elif t.startswith('px-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-left:{n}px'); decls.append(f'padding-right:{n}px')
            except Exception:
                pass
        elif t.startswith('py-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-top:{n}px'); decls.append(f'padding-bottom:{n}px')
            except Exception:
                pass
        elif t.startswith('pt-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-top:{n}px')
            except Exception:
                pass
        elif t.startswith('pr-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-right:{n}px')
            except Exception:
                pass
        elif t.startswith('pb-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-bottom:{n}px')
            except Exception:
                pass
        elif t.startswith('pl-'):
            try:
                n = int(t.split('-',1)[1]); decls.append(f'padding-left:{n}px')
            except Exception:
                pass
        elif t == 'min-w-0':
            decls.append('min-width:0')
        # jc-* は子差分なので共通昇格しない
    # de-dup by prop
    prop_map = {}
    for d in decls:
        if ':' in d:
            k = d.split(':',1)[0].strip().lower()
            prop_map[k] = d
    return list(prop_map.values())


def _quantize_token(tok: str) -> str:
    # normalize g-/p*- tokens to nearest scale (4px grid with common steps)
    scales = [4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 80, 120, 420]
    def _q(n: int) -> int:
        # snap to nearest scale
        return min(scales, key=lambda s: abs(s - n))
    m = re.match(r"^(g|px|py|pt|pr|pb|pl)-(\d+)$", tok)
    if not m:
        return tok
    kind, num = m.group(1), int(m.group(2))
    qn = _q(num)
    return f"{kind}-{qn}"


def _quantize_class_tokens(cls: str) -> str:
    parts = cls.split()
    out = []
    for p in parts:
        out.append(_quantize_token(p))
    return ' '.join(out)


def unify_eq_cols_children(html_path: Path, backup=False, promote_visuals: bool = False):
    """Under .eq-cols parent, compute intersection of common utility tokens across direct children.
    If intersection contains meaningful set (fx-col, padding/gap/min-w-0, etc.),
    emit a generic .row-item CSS with those decls and replace the covered tokens on children by .row-item.
    """
    try:
        text = html_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return False
    original = text
    lines = text.splitlines()
    parent_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\beq-cols\b[^\"]*)\"[^>]*>")
    section_re = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"[^>]*>", re.I)
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    changed = False
    i = 0
    while i < len(lines):
        pm = parent_re.match(lines[i])
        if not pm:
            i += 1
            continue
        indent = pm.group(1)
        close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
        # collect direct children
        kids = []
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                kids.append((j, cm.group(3)))
            j += 1
        if len(kids) >= 2:
            # compute intersection tokens (exclude jc- to keep child-specific main-axis alignment)
            token_sets = []
            # first quantize tokens inside class strings for tolerance, and rewrite lines
            qkids = []
            for idx, cls in kids:
                qcls = _quantize_class_tokens(cls)
                if qcls != cls:
                    lines[idx] = lines[idx].replace(cls, qcls, 1)
                    cls = qcls
                    changed = True
                ts = _extract_tokens(cls)
                token_sets.append(ts)
                qkids.append((idx, cls))
            inter = set.intersection(*token_sets) if token_sets else set()
            # remove jc-* from intersection to avoid overriding child intent
            inter = {t for t in inter if not t.startswith('jc-')}
            # candidates to cover: fx-col/fw-nowrap/ai-*/g-*/px*/py*/pt*/pb*/pl*/min-w-0
            cover = {t for t in inter if t.startswith(('fx-','fw-','ai-','g-','p','min-w-'))}
            # minimal usefulness: need at least fx-col and何らかのpadding/gap/min-w-0
            has_layout = any(t.startswith('fx-') for t in cover)
            has_space = any(t.startswith(('g-','px-','py-','pt-','pr-','pb-','pl-','min-w-')) for t in cover)
            if has_layout and has_space:
                # ensure style-common.css has .row-item rule with these decls
                decls = _tokens_to_css(cover)
                if decls:
                    try:
                        style_common = html_path.parent / 'style-common.css'
                        css = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
                        rule = f"\n/* row-item (auto) */\n:where(.row-item){{{'; '.join(decls)} }}\n"
                        if rule not in css:
                            with style_common.open('a', encoding='utf-8') as f:
                                f.write(rule)
                    except Exception:
                        pass
                    # also emit section-scoped alias e.g., about__row-item and append to children
                    try:
                        # find nearest preceding section line to infer section key
                        sec_name = None
                        k = i
                        while k >= 0 and sec_name is None:
                            ms = section_re.search(lines[k])
                            if ms:
                                scls = ms.group(1).split()
                                sec_name = scls[0] if scls else None
                                break
                            k -= 1
                        if sec_name:
                            sec_alias = f"{sec_name}__row-item"
                            scss = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
                            sec_rule = f"\n/* row-item (section) */\n:where(.{sec_alias}){{{'; '.join(decls)} }}\n"
                            if sec_rule not in scss:
                                with style_common.open('a', encoding='utf-8') as f:
                                    f.write(sec_rule)
                            # add alias to each child line
                            for idx, cls in kids:
                                if sec_alias not in lines[idx]:
                                    lines[idx] = lines[idx].replace(cls, cls + ' ' + sec_alias, 1)
                                    changed = True
                    except Exception:
                        pass
                    # Promote common visuals when requested, or when this looks like a card cluster under eq-cols
                    try:
                        css_path = html_path.parent / 'style.css'
                        visuals = {'background-color','box-shadow','border-radius'}
                        vis_map = parse_css_class_props(css_path, visuals)
                        kid_selectors = set()
                        kids_classes = []
                        for _, cls in qkids:
                            kids_classes.append(cls)
                            for t in cls.split():
                                if t.startswith('n-'):
                                    kid_selectors.add('.'+t)
                        vis_props_list = []
                        for sel in kid_selectors:
                            vp = vis_map.get(sel)
                            if vp:
                                vis_props_list.append(vp)
                        # Only promote visuals when explicitly enabled via flag/env
                        if promote_visuals and vis_props_list:
                            keys = set.intersection(*[set(vp.keys()) for vp in vis_props_list]) if vis_props_list else set()
                            common_vis = {}
                            for k in sorted(keys):
                                v0 = vis_props_list[0].get(k)
                                if all(vp.get(k) == v0 for vp in vis_props_list[1:]):
                                    common_vis[k] = v0
                            if common_vis:
                                # Do not auto-write global alias visuals by default to avoid unintended spread
                                # Intentionally disabled unless a targeted selector strategy is introduced.
                                pass
                    except Exception:
                        pass
                    # replace tokens on each child with .row-item and derived __* modifiers
                    for idx, cls in qkids:
                        toks = cls.split()
                        new_toks = []
                        covered = set(cover)
                        jc_mod = None
                        if 'jc-center' in toks:
                            jc_mod = '__center'
                        elif 'jc-flex-end' in toks:
                            jc_mod = '__end'
                        elif 'jc-space-between' in toks:
                            jc_mod = '__between'
                        toks = [t for t in toks if not t.startswith('jc-')]
                        for t in toks:
                            if t in covered:
                                continue
                            new_toks.append(t)
                        # Prefer section-scoped alias over generic .row-item to reduce token noise
                        has_sec_alias = False
                        try:
                            if sec_name:
                                sec_alias = f"{sec_name}__row-item"
                                has_sec_alias = sec_alias in ' ' + lines[idx] + ' '
                        except Exception:
                            has_sec_alias = False
                        if not has_sec_alias and 'row-item' not in new_toks:
                            new_toks.append('row-item')
                        if jc_mod and jc_mod not in new_toks:
                            new_toks.append(jc_mod)
                        new_cls = ' '.join(new_toks)
                        lines[idx] = lines[idx].replace(cls, new_cls, 1)
                        changed = True
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        # backup
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")
    return changed


def unify_non_eq_row_children(html_path: Path, backup: bool = False):
    """Consolidate common utility tokens across siblings under fx-row parents that are NOT marked eq-cols.
    Conservative: only promote layout/spacing tokens (fx-*, fw-*, ai-*, g-*, p*, min-w-0) and never touch visuals.
    Replace covered tokens on children with a shared .row-item and section alias.
    """
    try:
        text = html_path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        return False
    original = text
    lines = text.splitlines()
    parent_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]*\bfx-row\b[^\"]*)\"[^>]*>")
    child_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    section_re = re.compile(r"<section\b[^>]*\bclass=\"([^\"]+)\"", re.I)
    close_re_tpl = r"^{indent}</div>\s*$"
    changed = False
    i = 0
    while i < len(lines):
        m = parent_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        # skip eq-cols parents; handled elsewhere
        if ' eq-cols ' in (' ' + classes + ' '):
            # jump past this block quickly
            close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
            j = i + 1
            while j < len(lines) and not close_re.match(lines[j]):
                j += 1
            i = j if j > i else i + 1
            continue
        close_re = re.compile(close_re_tpl.format(indent=re.escape(indent)))
        kids: list[tuple[int, str]] = []
        j = i + 1
        while j < len(lines) and not close_re.match(lines[j]):
            cm = child_re.match(lines[j])
            if cm and cm.group(1) == indent + '  ':
                kids.append((j, cm.group(3)))
            j += 1
        if len(kids) < 2:
            i = j if j > i else i + 1
            continue
        # compute token intersection across children (conservative set)
        def _extract_tokens(cls: str) -> set[str]:
            return set(cls.split())
        token_sets = []
        qkids: list[tuple[int, str]] = []
        for idx, cls in kids:
            ts = _extract_tokens(cls)
            token_sets.append(ts)
            qkids.append((idx, cls))
        inter = set.intersection(*token_sets) if token_sets else set()
        # remove jc-* to keep per-child intent
        inter = {t for t in inter if not t.startswith('jc-')}
        cover = {t for t in inter if t.startswith(('fx-','fw-','ai-','g-','p','min-w-'))}
        has_layout = any(t.startswith('fx-') for t in cover)
        has_space = any(t.startswith(('g-','px-','py-','pt-','pr-','pb-','pl-','min-w-')) for t in cover)
        if not (has_layout and has_space):
            i = j if j > i else i + 1
            continue
        # ensure style-common.css has .row-item rule with these decls
        decls = _tokens_to_css(cover)
        if decls:
            try:
                style_common = html_path.parent / 'style-common.css'
                css = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
                rule = f"\n/* row-item (auto non-eq) */\n:where(.row-item){{{'; '.join(decls)} }}\n"
                if rule not in css:
                    with style_common.open('a', encoding='utf-8') as f:
                        f.write(rule)
            except Exception:
                pass
            # also emit section-scoped alias and append to children
            try:
                sec_name = None
                k = i
                while k >= 0 and sec_name is None:
                    ms = section_re.search(lines[k])
                    if ms:
                        scls = ms.group(1).split()
                        sec_name = scls[0] if scls else None
                        break
                    k -= 1
                if sec_name:
                    sec_alias = f"{sec_name}__row-item"
                    scss = style_common.read_text(encoding='utf-8', errors='ignore') if style_common.exists() else ''
                    sec_rule = f"\n/* row-item (section non-eq) */\n:where(.{sec_alias}){{{'; '.join(decls)} }}\n"
                    if sec_rule not in scss:
                        with style_common.open('a', encoding='utf-8') as f:
                            f.write(sec_rule)
                    for idx, cls in kids:
                        if sec_alias not in lines[idx]:
                            lines[idx] = lines[idx].replace(cls, cls + ' ' + sec_alias, 1)
                            changed = True
            except Exception:
                pass
            # replace covered tokens on each child with .row-item and derived jc-* modifiers preserved as __*
            for idx, cls in qkids:
                toks = cls.split()
                new_toks = []
                jc_mod = None
                if 'jc-center' in toks:
                    jc_mod = '__center'
                elif 'jc-flex-end' in toks:
                    jc_mod = '__end'
                elif 'jc-space-between' in toks:
                    jc_mod = '__between'
                toks = [t for t in toks if not t.startswith('jc-')]
                for t in toks:
                    if t in cover:
                        continue
                    new_toks.append(t)
                # Prefer section-scoped alias over generic .row-item
                has_sec_alias = False
                try:
                    if sec_name:
                        sec_alias = f"{sec_name}__row-item"
                        has_sec_alias = sec_alias in ' ' + lines[idx] + ' '
                except Exception:
                    has_sec_alias = False
                if not has_sec_alias and 'row-item' not in new_toks:
                    new_toks.append('row-item')
                if jc_mod and jc_mod not in new_toks:
                    new_toks.append(jc_mod)
                new_cls = ' '.join(new_toks)
                lines[idx] = lines[idx].replace(cls, new_cls, 1)
                changed = True
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding='utf-8')
        html_path.write_text(new_text, encoding='utf-8')
    return changed


def collect_eq_cols_n_classes(root: Path) -> set[str]:
    nset: set[str] = set()
    parent_re = re.compile(r"<(div)[^>]*\bclass=\"[^\"]*\beq-cols\b[^\"]*\"[^>]*>")
    child_re = re.compile(r"<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    for hp in find_html_files(root):
        try:
            text = hp.read_text(encoding='utf-8', errors='ignore')
        except Exception:
            continue
        # quick scan within file: if eq-cols present, collect direct child n- tokens by line structure (best-effort)
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            if parent_re.search(lines[i]):
                indent = re.match(r"^(\s*)", lines[i]).group(1) if re.match(r"^(\s*)", lines[i]) else ''
                close_re = re.compile(rf"^{re.escape(indent)}</div>\\s*$")
                j = i + 1
                while j < len(lines) and not close_re.match(lines[j]):
                    cm = child_re.search(lines[j])
                    if cm and lines[j].startswith(indent + '  '):
                        for c in cm.group(2).split():
                            if c.startswith('n-'):
                                nset.add('.' + c)
                    j += 1
                i = j
            i += 1
    return nset


def comment_out_min_height_for(root: Path, selectors: set[str], backup=False):
    css_path = root / 'style.css'
    if not css_path.exists() or not selectors:
        return
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    original = css
    out_lines = []
    in_rule = False
    brace_depth = 0
    rule_targets = False
    current_selectors = ''
    for line in css.splitlines():
        stripped = line.strip()
        if not in_rule:
            if '{' in line:
                in_rule = True
                brace_depth = 1
                current_selectors = line.split('{',1)[0]
                # check if selector contains any of target selectors
                sel_classes = set(re.findall(r"\.[a-zA-Z0-9_-]+", current_selectors))
                rule_targets = any(sc in selectors for sc in sel_classes)
            out_lines.append(line)
            continue
        else:
            if '{' in line:
                brace_depth += line.count('{')
            if '}' in line:
                brace_depth -= line.count('}')
                out_lines.append(line)
                if brace_depth <= 0:
                    in_rule = False
                    rule_targets = False
                continue
            if rule_targets and stripped.lower().startswith('min-height:'):
                out_lines.append('/* eq-cols drop: ' + stripped + ' */')
            else:
                out_lines.append(line)
    new_css = "\n".join(out_lines) + "\n"
    if new_css != original:
        if backup:
            css_path.with_suffix(css_path.suffix + '.minh.bak').write_text(original, encoding='utf-8')
        css_path.write_text(new_css, encoding='utf-8')


def drop_row_item_when_alias_present(html_path: Path, backup: bool = False):
    """If a class attribute contains both a section-scoped alias '*__row-item' and the generic 'row-item',
    drop the generic one to reduce noise (structure-first readability)."""
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        has_alias = any('__row-item' in c for c in arr)
        if not has_alias:
            return m.group(0)
        filtered = [c for c in arr if c != 'row-item']
        if filtered == arr:
            return m.group(0)
        return before + ' '.join(filtered) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def drop_default_jc_and_fw(html_path: Path, backup: bool = False):
    """Drop default flex tokens from class attributes to improve readability:
    - 'jc-flex-start' (default justify-content)
    - 'fw-nowrap' (default flex-wrap)
    Only removes class tokens; does not touch CSS.
    """
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        filtered = [c for c in arr if c not in ('jc-flex-start', 'fw-nowrap')]
        if filtered == arr:
            return m.group(0)
        return before + ' '.join(filtered) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def dedupe_col_macros(html_path: Path, backup: bool = False):
    """If both col-center and col-start exist on the same element, drop col-center and keep col-start.
    They conflict on align-items; prefer explicit start when both present.
    """
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        if 'col-center' in arr and 'col-start' in arr:
            arr = [c for c in arr if c != 'col-center']
        return before + ' '.join(arr) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def collapse_col_macro_tokens(html_path: Path, backup: bool = False):
    """If col-center or col-start macro is present, remove the underlying fx-col/ai-* tokens for readability."""
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        s = set(arr)
        if 'col-center' in s:
            arr = [c for c in arr if c not in ('fx-col','ai-center','ai-flex-start')]
        if 'col-start' in s:
            arr = [c for c in arr if c not in ('fx-col','ai-flex-start','ai-center')]
        return before + ' '.join(arr) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def drop_padding_tokens_when_card_alias(html_path: Path, backup: bool = False):
    """If an element has a section-scoped card alias (*__card) or generic about__card, remove px-/py-/pt-/pr-/pb-/pl- tokens
    to avoid conflicts with alias-provided padding and reduce class noise."""
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        if not any(c.endswith('__card') or c == 'about__card' for c in arr):
            return m.group(0)
        filtered = [c for c in arr if not c.startswith(('px-','py-','pt-','pr-','pb-','pl-'))]
        if filtered == arr:
            return m.group(0)
        return before + ' '.join(filtered) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def merge_col_start_jc_center(html_path: Path, backup: bool = False):
    """Replace 'col-start' + 'jc-center' with 'stack-center' to reduce token noise.
    Requires that a macro for 'stack-center' exists (fx-col + ai-flex-start + jc-center).
    """
    text = html_path.read_text(encoding='utf-8', errors='ignore')
    original = text
    class_re = re.compile(r'(class=\")([^\"]+)(\")')
    def repl(m: re.Match) -> str:
        before, classes, after = m.group(1), m.group(2), m.group(3)
        arr = classes.split()
        if 'col-start' in arr and 'jc-center' in arr:
            arr = [c for c in arr if c not in ('col-start','jc-center')]
            if 'stack-center' not in arr:
                arr.append('stack-center')
        return before + ' '.join(arr) + after
    text2 = class_re.sub(repl, text)
    if text2 != original:
        if backup:
            html_path.with_suffix(html_path.suffix + '.bak').write_text(original, encoding='utf-8')
        html_path.write_text(text2, encoding='utf-8')


def comment_out_props_for(css_path: Path, selectors: set[str], props: list[str], backup=False):
    if not css_path.exists() or not selectors or not props:
        return
    css = css_path.read_text(encoding='utf-8', errors='ignore')
    original = css
    out_lines = []
    in_rule = False
    brace_depth = 0
    rule_targets = False
    current_selectors = ''
    prop_set = {p.strip().lower()+":" for p in props}
    for line in css.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        if not in_rule:
            if '{' in line:
                in_rule = True
                brace_depth = 1
                current_selectors = line.split('{',1)[0]
                sel_classes = set(re.findall(r"\.[a-zA-Z0-9_-]+", current_selectors))
                rule_targets = any(sc in selectors for sc in sel_classes)
            out_lines.append(line)
            continue
        else:
            if '{' in line:
                brace_depth += line.count('{')
            if '}' in line:
                brace_depth -= line.count('}')
                out_lines.append(line)
                if brace_depth <= 0:
                    in_rule = False
                    rule_targets = False
                continue
            if rule_targets and any(low.startswith(ps) for ps in prop_set):
                out_lines.append('/* unify-vis drop: ' + stripped + ' */')
            else:
                out_lines.append(line)
    new_css = "\n".join(out_lines) + "\n"
    if new_css != original:
        if backup:
            css_path.with_suffix(css_path.suffix + '.vis.bak').write_text(original, encoding='utf-8')
        css_path.write_text(new_css, encoding='utf-8')


def add_data_mh_groups(html_path: Path, backup=False):
    """Add data-mh="cardNN" to card-like repeated siblings.
    Heuristics:
      - Under same parent, repeated children whose class contains 'menu' (>=2)
      - Or parent has layout-3col/layout-4col and children with 'frame' (>=2)
    Each detected group gets a sequential group id card01, card02, ... (per file).
    """
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    original = text
    lines = text.splitlines()
    open_re = re.compile(r"^(\s*)<div[^>]*\bclass=\"([^\"]+)\"[^>]*>")
    close_tpl = r"^{indent}</div>\s*$"
    child_open_re = re.compile(r"^(\s*)<([a-zA-Z]+)\b[^>]*\bclass=\"([^\"]+)\"([^>]*)>")
    group_idx = 0
    i = 0
    changed = False
    while i < len(lines):
        m = open_re.match(lines[i])
        if not m:
            i += 1
            continue
        indent = m.group(1)
        classes = m.group(2)
        is_grid_parent = ("layout-3col" in classes) or ("layout-4col" in classes)
        close_re = re.compile(close_tpl.format(indent=re.escape(indent)))
        # scan children until close
        child_idxs = []
        j = i + 1
        while j < len(lines):
            if close_re.match(lines[j]):
                break
            cm = child_open_re.match(lines[j])
            if cm:
                child_idxs.append(j)
            j += 1
        # build groups by keyword
        menu_children = [idx for idx in child_idxs if ' menu ' in (' '+child_open_re.match(lines[idx]).group(3)+' ')]
        groups = []
        if len(menu_children) >= 2:
            groups.append(menu_children)
        if is_grid_parent:
            frame_children = [idx for idx in child_idxs if ' frame' in (' '+child_open_re.match(lines[idx]).group(3))]
            if len(frame_children) >= 2:
                groups.append(frame_children)
        # assign data-mh
        for grp in groups:
            group_idx += 1
            mh = f"card{group_idx:02d}"
            for idx in grp:
                cm = child_open_re.match(lines[idx])
                if not cm:
                    continue
                attrs = cm.group(4)
                # skip if already has data-mh
                if re.search(r"\bdata-mh=\"[^\"]+\"", attrs):
                    continue
                # add data-mh before closing '>' of the tag line
                lines[idx] = lines[idx].rstrip('>') + f' data-mh="{mh}">'
                changed = True
        i = j if j > i else i + 1
    if changed:
        new_text = "\n".join(lines) + "\n"
        if backup:
            html_path.with_suffix(html_path.suffix + ".bak").write_text(original, encoding="utf-8")
        html_path.write_text(new_text, encoding="utf-8")


def comment_out_in_style_css(css_path: Path, applied_classes: set, covered_props: set, backup=False):
    if not css_path.exists():
        return
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    original = css
    # very conservative: inside a rule for .n-xxxxx / .layout-* / .frame-*, comment out lines that exactly match covered flex props
    def prop_line_regex(prop):
        return re.compile(rf"(^|\s){re.escape(prop)}\s*:\s*[^;]+;\s*$", re.I)

    covered_res = {p: prop_line_regex(p) for p in covered_props}
    # extra: inside .layout-2col image-leading rules, also comment out max-width/width lines
    mw_re = prop_line_regex("max-width")
    w_re = prop_line_regex("width")
    out_lines = []
    in_rule = False
    rule_targets = False
    brace_depth = 0
    current_selectors = ""
    for line in css.splitlines():
        stripped = line.strip()
        if not in_rule:
            if "{" in line:
                in_rule = True
                brace_depth = 1
                current_selectors = line.split("{" ,1)[0]
                # check if selector contains any class we touched
                sel_classes = set(re.findall(r"\.[a-zA-Z0-9_-]+", current_selectors))
                rule_targets = any(sc in applied_classes for sc in sel_classes)
                # special-case: rules targeting first-column images under layout-2col
                sel_str = current_selectors
                is_img_lead = (".layout-2col" in sel_str) and ("> :first-child img" in sel_str or "> .img img" in sel_str or "> .image img" in sel_str)
            out_lines.append(line)
            continue
        else:
            # inside rule
            if "{" in line:
                brace_depth += line.count("{")
            if "}" in line:
                brace_depth -= line.count("}")
                out_lines.append(line)
                if brace_depth <= 0:
                    in_rule = False
                    rule_targets = False
                continue
            if rule_targets:
                # comment out covered lines
                commented = False
                for prop, reg in covered_res.items():
                    if reg.search(stripped):
                        out_lines.append("/* dedup: " + stripped + " */")
                        commented = True
                        break
                if not commented:
                    # additionally for image-leading rules
                    if 'is_img_lead' in locals() and is_img_lead and (mw_re.search(stripped) or w_re.search(stripped)):
                        out_lines.append("/* dedup-img: " + stripped + " */")
                    else:
                        out_lines.append(line)
            else:
                # even if not rule_targets, still neutralize image-leading width rules under layout-2col
                if 'is_img_lead' in locals() and is_img_lead and (mw_re.search(stripped) or w_re.search(stripped)):
                    out_lines.append("/* dedup-img: " + stripped + " */")
                else:
                    out_lines.append(line)

    new_css = "\n".join(out_lines) + "\n"
    if new_css != original:
        if backup:
            css_path.with_suffix(css_path.suffix + ".bak").write_text(original, encoding="utf-8")
        css_path.write_text(new_css, encoding="utf-8")


def rewrite_positional_selectors(css_path: Path, backup=False):
    """Rewrite fragile positional selectors to role-based ones.
    Currently: .layout-2col > :first-child  ->  .layout-2col > .col-first
    (non-destructive backup, plain text replacement; keeps formatting)
    """
    if not css_path.exists():
        return
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    original = css
    # simple, safe replacements
    # 1) :first-child -> BEM first element (keep .layout-2col context, switch to descendant)
    css = re.sub(r"(\.layout-2col)\s*>\s*:first-child", r"\1 .layout-2col__col--first", css)
    css = re.sub(r"(\.layout-2col)>(\s*):first-child", r"\1 \2.layout-2col__col--first", css)
    # 2) direct-child .col-first -> BEM first element
    css = re.sub(r"(\.layout-2col)\s*>\s*\.col-first", r"\1 .layout-2col__col--first", css)
    # 3) descendant .col-first -> BEM first element
    css = re.sub(r"(\.layout-2col)\s+\.col-first", r"\1 .layout-2col__col--first", css)
    # 4) .col-second variants -> BEM second element
    css = re.sub(r"(\.layout-2col)\s*>\s*\.col-second", r"\1 .layout-2col__col--second", css)
    css = re.sub(r"(\.layout-2col)\s+\.col-second", r"\1 .layout-2col__col--second", css)
    # 5) fix selectors that lost '.' accidentally in previous passes
    css = re.sub(r"(?<![.#\w-])(layout-2col__col--first)", r".\1", css)
    css = re.sub(r"(?<![.#\w-])(layout-2col__col--second)", r".\1", css)
    if css != original:
        if backup:
            css_path.with_suffix(css_path.suffix + ".bak").write_text(original, encoding="utf-8")
        css_path.write_text(css, encoding="utf-8")


def main():
    args = parse_args()
    root = Path(args.root)
    prop_list = [s.strip() for s in (args.props or "").split(",") if s.strip()]
    html_files = find_html_files(root)
    all_instances = []
    for hp in html_files:
        all_instances.extend(scan_html(hp, prop_list))
    buckets = build_buckets(all_instances, args.min_occurs)

    # plan utilities needed
    needed_utils = set()
    for b in buckets.values():
        needed_utils.update(util_classes_for(b["props"]))

    # write buckets report
    report = {
        "min_occurs": args.min_occurs,
        "props": prop_list,
        "buckets": [
            {
                "props": b["props"],
                "util_classes": util_classes_for(b["props"]),
                "count": len(b["items"]),
            }
            for b in buckets.values()
        ],
    }
    (root / "style-buckets.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        return

    # Also include any utility tokens explicitly present in HTML classes
    needed_utils.update(collect_util_tokens_from_html(root))

    # Always (re)write style-common.css with baseline rules (eq-cols, responsive, helpers)
    # We avoid injecting classes to HTML unless --inject-css is set.
    write_style_common(root, needed_utils)
    css_class_map = parse_css_class_props(root / "style.css", set(FLEX_PROPS)) if args.inject_css else {}

    applied_classes = set()
    eq_cols_n_classes: set[str] = set()
    for hp in html_files:
        # ensure fullbleed wrapper structure first
        ensure_fullbleed_content_wrapper(hp, backup=args.backup)
        # add role classes before utility injection to avoid positional selectors
        add_two_col_role_classes(hp, backup=args.backup)
        # If injecting, add link and utilities; otherwise skip
        if args.inject_css:
            inject_link_and_classes(hp, css_class_map, set(FLEX_PROPS), backup=args.backup)
        # add eq-cols for fx-row parents with 2–4 children (layout-driven equalization)
        add_eq_cols_to_rows(hp, backup=args.backup)
        # normalize equalized rows to drop redundant child height/self-alignment; enforce ai-stretch on parent
        normalize_eq_cols_rows(hp, backup=args.backup)
        # unify eq-cols children by promoting common tokens to .row-item and dropping covered tokens
        unify_eq_cols_children(hp, backup=args.backup, promote_visuals=(args.promote_visuals or (os.getenv('PROMOTE_VISUALS','false').lower()=='true')))
        # optionally consolidate non-eq fx-row siblings
        if args.consolidate_non_eq or (os.getenv('CONSOLIDATE_NON_EQ','false').lower()=='true'):
            unify_non_eq_row_children(hp, backup=args.backup)
        # cleanup: if alias present, drop generic row-item; also drop default jc-flex-start/fw-nowrap
        drop_row_item_when_alias_present(hp, backup=args.backup)
        drop_default_jc_and_fw(hp, backup=args.backup)
        dedupe_col_macros(hp, backup=args.backup)
        collapse_col_macro_tokens(hp, backup=args.backup)
        drop_padding_tokens_when_card_alias(hp, backup=args.backup)
        merge_col_start_jc_center(hp, backup=args.backup)
        # collect n-* used under eq-cols for CSS min-height neutralization
        eq_cols_n_classes |= collect_eq_cols_n_classes(root)
    # drop min-height for those n-* in CSS (safe under eq-cols)
    comment_out_min_height_for(root, eq_cols_n_classes, backup=args.backup)

    # collect n- classes present for optional css commenting
    for hp in html_files:
        text = hp.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"class=\"([^\"]+)\"", text):
            for c in m.group(1).split():
                if c.startswith("n-") or c.startswith("layout-") or c.startswith("frame"):
                    applied_classes.add('.'+c)
    if args.comment_out_covered:
        # very conservative: only comment display/flex-direction/gap/align-items/justify-content
        covered = {"display", "flex-direction", "gap", "align-items", "justify-content"}
        # process common CSS files if present
        for css_name in ("style.css", "style-pc.css", "style-sp.css"):
            css_path = root / css_name
            comment_out_in_style_css(css_path, applied_classes, covered, backup=args.backup)
            # rewrite positional selectors to role-based ones
            rewrite_positional_selectors(css_path, backup=args.backup)

    # Optional: drop n-* from HTML when fully covered by utilities/BEM/style-common.css
    try:
        drop_n_flag = (os.getenv('DROP_N_IF_COVERED', 'false') or 'false').lower() == 'true'
        if drop_n_flag:
            subprocess.run(["python3", "tools/drop_n_if_covered.py", "--root", str(root), "--backup"], check=False)
    except Exception:
        pass

    # Sectionize (wrapper mode) independent of inject-css
    if args.sectionize:
        exclude_roles = set([s.strip().lower() for s in (args.exclude_roles or "").split(",") if s.strip()])
        for hp in html_files:
            sectionize_safe(hp, require_heading=args.require_heading, min_children=args.min_children, exclude_roles=exclude_roles, backup=args.backup)
        # After sectionizing, add data-mh groups to repeated card-like rows
        for hp in html_files:
            add_data_mh_groups(hp, backup=args.backup)


if __name__ == "__main__":
    main()
