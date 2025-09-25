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
    # Prefer role class over positional selector to avoid nth-child fragility
    lines.append(":where(.layout-2col)>.col-first img{max-width:100% !important}")
    # Fallback for environments where role class is未付与（残置）
    lines.append(":where(.layout-2col)>:first-child img{max-width:100% !important}")
    out = root / "style-common.css"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


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
        text = re.sub(
            r"(<head[^>]*>)",
            r"\\1\n    <link rel=\"stylesheet\" href=\"style-common.css\">",
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
            classes.append(role)
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


def comment_out_in_style_css(css_path: Path, applied_classes: set, covered_props: set, backup=False):
    if not css_path.exists():
        return
    css = css_path.read_text(encoding="utf-8", errors="ignore")
    original = css
    # very conservative: inside a rule for .n-xxxxx / .layout-* / .frame-*, comment out lines that exactly match covered flex props
    def prop_line_regex(prop):
        return re.compile(rf"(^|\s){re.escape(prop)}\s*:\s*[^;]+;\s*$", re.I)

    covered_res = {p: prop_line_regex(p) for p in covered_props}
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
                    out_lines.append(line)
            else:
                out_lines.append(line)

    new_css = "\n".join(out_lines) + "\n"
    if new_css != original:
        if backup:
            css_path.with_suffix(css_path.suffix + ".bak").write_text(original, encoding="utf-8")
        css_path.write_text(new_css, encoding="utf-8")


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

    if args.inject_css and needed_utils:
        write_style_common(root, needed_utils)
        # build class->props map from style.css for augmentation
        css_class_map = parse_css_class_props(root / "style.css", set(FLEX_PROPS))
        # inject classes and link into all HTML files
        applied_classes = set()
        for hp in html_files:
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


if __name__ == "__main__":
    main()
