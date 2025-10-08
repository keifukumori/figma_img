#!/usr/bin/env python3
import argparse
import json
import os
import re
from pathlib import Path


FLEX_PROPS = [
    "display",
    "flex-direction",
    "justify-content",
    "align-items",
    "gap",
    "flex-wrap",
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
        v = ai[3:].replace("-", " ")
        lines.append(f":where(.{ai}){{align-items:{v};}}")
    jc_set = {u for u in needed_utils if u.startswith("jc-")}
    for jc in sorted(jc_set):
        v = jc[3:].replace("-", " ")
        lines.append(f":where(.{jc}){{justify-content:{v};}}")
    fw_set = {u for u in needed_utils if u.startswith("fw-")}
    for fw in sorted(fw_set):
        v = fw[3:].replace("-", " ")
        lines.append(f":where(.{fw}){{flex-wrap:{v};}}")
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
    out = root / "style-common.css"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# Tokens that our utilities know how to style even if they were not discovered from CSS props
UTIL_TOKEN_RE = re.compile(r"\b(?:fx-(?:row|col)|g-\d+|ai-(?:flex-start|center|flex-end)|jc-(?:flex-start|center|flex-end|space-between)|fw-(?:nowrap|wrap))\b")


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

    if args.inject_css:
        write_style_common(root, needed_utils)
        # build class->props map from style.css for augmentation
        css_class_map = parse_css_class_props(root / "style.css", set(FLEX_PROPS))
        # inject classes and link into all HTML files
        applied_classes = set()
        for hp in html_files:
            # ensure fullbleed wrapper structure first
            ensure_fullbleed_content_wrapper(hp, backup=args.backup)
            # add role classes before utility injection to avoid positional selectors
            add_two_col_role_classes(hp, backup=args.backup)
            inject_link_and_classes(hp, css_class_map, set(FLEX_PROPS), backup=args.backup)
            # collect n- classes present for optional css commenting
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
