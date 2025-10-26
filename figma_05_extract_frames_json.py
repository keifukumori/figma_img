import os
import json
import argparse
from datetime import datetime

from dotenv import load_dotenv


def sanitize_filename(name: str) -> str:
    s = name or ""
    bad = '<>:"/\\|?*\n\r\t'
    for ch in bad:
        s = s.replace(ch, "_")
    # collapse spaces and underscores a bit
    s = " ".join(s.split())
    s = s.replace(" ", "_")
    return s[:200] if len(s) > 200 else s


def find_node_by_id(node: dict, target_id: str):
    if not isinstance(node, dict):
        return None
    if node.get("id") == target_id:
        return node
    for child in node.get("children", []) or []:
        found = find_node_by_id(child, target_id)
        if found:
            return found
    return None


def iter_nodes(node: dict):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []) or []:
        if isinstance(child, dict):
            yield from iter_nodes(child)


def collect_used_style_ids(root: dict) -> set:
    ids = set()
    for n in iter_nodes(root):
        # Direct *StyleId props
        for k, v in list(n.items()):
            if isinstance(k, str) and k.endswith("StyleId") and isinstance(v, str):
                ids.add(v)
        # styles: { fill, stroke, effect, text, grid }
        styles_obj = n.get("styles")
        if isinstance(styles_obj, dict):
            for v in styles_obj.values():
                if isinstance(v, str):
                    ids.add(v)
    return ids


def collect_used_component_ids(root: dict) -> set:
    ids = set()
    for n in iter_nodes(root):
        cid = n.get("componentId")
        if isinstance(cid, str):
            ids.add(cid)
    return ids


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------- Chat-friendly pruning helpers ----------------
def _round_number(x, digits: int):
    try:
        return round(float(x), digits)
    except Exception:
        return x


def _round_json_inplace(obj, digits: int):
    if digits is None:
        return obj
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            obj[k] = _round_json_inplace(v, digits)
        return obj
    if isinstance(obj, list):
        for i in range(len(obj)):
            obj[i] = _round_json_inplace(obj[i], digits)
        return obj
    if isinstance(obj, float):
        return _round_number(obj, digits)
    return obj


def _color_summary(c: dict, digits: int):
    if not isinstance(c, dict):
        return c
    out = {}
    for k in ("r", "g", "b", "a"):
        if k in c:
            out[k] = _round_number(c[k], digits)
    return out


def _paint_summary(p: dict, digits: int):
    if not isinstance(p, dict):
        return p
    t = p.get("type")
    out = {k: p[k] for k in ("type", "visible", "opacity", "blendMode") if k in p}
    if t == "SOLID" and isinstance(p.get("color"), dict):
        out["color"] = _color_summary(p["color"], digits)
    elif t and t.startswith("GRADIENT"):
        stops = []
        for s in p.get("gradientStops", []) or []:
            if not isinstance(s, dict):
                continue
            stops.append({
                "position": _round_number(s.get("position"), digits) if isinstance(s.get("position"), (int, float)) else s.get("position"),
                "color": _color_summary((s.get("color") or {}), digits),
            })
        if stops:
            out["gradientStops"] = stops
    elif t == "IMAGE":
        for k in ("imageRef", "scaleMode"):
            if k in p:
                out[k] = p[k]
    return out


def _effect_summary(e: dict, digits: int):
    if not isinstance(e, dict):
        return e
    out = {k: e[k] for k in ("type", "visible", "blendMode") if k in e}
    for k in ("radius", "spread"):
        if k in e:
            out[k] = _round_number(e[k], digits)
    if isinstance(e.get("offset"), dict):
        out["offset"] = {ax: _round_number(e["offset"].get(ax), digits) for ax in ("x", "y") if ax in e["offset"]}
    if isinstance(e.get("color"), dict):
        out["color"] = _color_summary(e["color"], digits)
    return out


ALLOWED_COMMON_KEYS = {
    "id", "name", "type", "visible", "opacity", "blendMode", "isMask",
    "absoluteBoundingBox", "constraints", "backgroundColor",
    "cornerRadius", "rectangleCornerRadii", "rotation",
    "strokeAlign", "strokeWeight", "strokeMiterAngle", "strokeCap", "strokeJoin",
    "layoutAlign", "layoutGrow", "layoutGrids", "clipsContent",
    "styles", "componentId",
}

ALLOWED_LAYOUT_KEYS = {
    "layoutMode", "primaryAxisSizingMode", "counterAxisSizingMode",
    "primaryAxisAlignItems", "counterAxisAlignItems",
    "itemSpacing", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "layoutWrap", "overflowDirection", "layoutPositioning",
    "minWidth", "maxWidth", "minHeight", "maxHeight",
}

ALLOWED_TEXT_STYLE_KEYS = {
    "fontFamily", "fontPostScriptName", "fontWeight", "fontSize",
    "textAutoResize", "textAlignHorizontal", "textAlignVertical",
    "lineHeightPx", "lineHeightPercent", "lineHeightUnit",
    "letterSpacing", "paragraphSpacing", "paragraphIndent",
}


def _prune_text_style(style: dict, digits: int):
    if not isinstance(style, dict):
        return style
    out = {}
    for k in ALLOWED_TEXT_STYLE_KEYS:
        if k in style:
            v = style[k]
            if isinstance(v, (int, float)):
                v = _round_number(v, digits)
            out[k] = v
    # Keep fills for text color if present (summarized)
    if isinstance(style.get("fills"), list):
        out["fills"] = [_paint_summary(p, digits) for p in style["fills"] if isinstance(p, dict)]
    return out


def prune_node_for_chat(node: dict, *, round_digits: int = 1, keep_vectors: bool = False) -> dict:
    if not isinstance(node, dict):
        return node
    out = {}
    # Copy allowed keys if present
    for k in ALLOWED_COMMON_KEYS | ALLOWED_LAYOUT_KEYS:
        if k in node:
            out[k] = node[k]
    # Fills / Strokes / Effects summaries
    if isinstance(node.get("fills"), list):
        out["fills"] = [_paint_summary(p, round_digits) for p in node["fills"] if isinstance(p, dict)]
    if isinstance(node.get("strokes"), list):
        out["strokes"] = [_paint_summary(s, round_digits) for s in node["strokes"] if isinstance(s, dict)]
    if isinstance(node.get("effects"), list):
        out["effects"] = [_effect_summary(e, round_digits) for e in node["effects"] if isinstance(e, dict)]
    # Text specifics
    if node.get("type") == "TEXT":
        for k in ("characters",):
            if k in node:
                out[k] = node[k]
        if isinstance(node.get("style"), dict):
            out["style"] = _prune_text_style(node["style"], round_digits)
    # Drop heavy vector geometries unless requested
    if keep_vectors:
        for k in ("vectorNetwork", "vectorPaths", "fillGeometry", "strokeGeometry"):
            if k in node:
                out[k] = node[k]
    # Recurse children
    children = node.get("children")
    if isinstance(children, list):
        out["children"] = [prune_node_for_chat(c, round_digits=round_digits, keep_vectors=keep_vectors) for c in children if isinstance(c, dict)]
    # Round numeric values for cleanliness
    _round_json_inplace(out, round_digits)
    return out


def prune_bundle_for_chat(bundle: dict, *, round_digits: int = 1, keep_vectors: bool = False) -> dict:
    if not isinstance(bundle, dict):
        return bundle
    out = {
        k: bundle.get(k)
        for k in ("source_file_name", "schemaVersion", "frame_node_id", "frame_name", "exported_at")
        if k in bundle
    }
    frame = bundle.get("frame")
    if isinstance(frame, dict):
        out["frame"] = prune_node_for_chat(frame, round_digits=round_digits, keep_vectors=keep_vectors)
    refs = bundle.get("refs")
    if isinstance(refs, dict):
        refs_out = {}
        if isinstance(refs.get("styles"), dict):
            refs_out["styles"] = refs["styles"]
        if isinstance(refs.get("components_meta"), dict):
            refs_out["components_meta"] = refs["components_meta"]
        if isinstance(refs.get("component_sets_meta"), dict):
            refs_out["component_sets_meta"] = refs["component_sets_meta"]
        if isinstance(refs.get("component_nodes"), list):
            refs_out["component_nodes"] = [
                prune_node_for_chat(n, round_digits=round_digits, keep_vectors=keep_vectors)
                if isinstance(n, dict) else n for n in refs["component_nodes"]
            ]
        if refs_out:
            out["refs"] = refs_out
    _round_json_inplace(out, round_digits)
    return out


def build_frame_bundle(
    file_data: dict,
    frame_node_id: str,
    include_styles: bool = True,
    components_mode: str = "meta",  # one of: none, meta, full
) -> dict:
    doc = file_data.get("document", {})
    frame = find_node_by_id(doc, frame_node_id)
    if not frame:
        raise SystemExit(f"Frame node-id not found: {frame_node_id}")

    bundle = {
        "source_file_name": file_data.get("name"),
        "schemaVersion": file_data.get("schemaVersion"),
        "frame_node_id": frame_node_id,
        "frame_name": frame.get("name"),
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "frame": frame,
    }

    # Collect and embed minimal external refs used by the frame
    refs = {}

    # Styles subset
    if include_styles:
        used_style_ids = collect_used_style_ids(frame)
        all_styles = file_data.get("styles") or {}
        if used_style_ids and isinstance(all_styles, dict):
            subset = {sid: all_styles[sid] for sid in used_style_ids if sid in all_styles}
            if subset:
                refs["styles"] = subset

    # Components: meta and optionally full component nodes
    used_comp_ids = collect_used_component_ids(frame)
    if components_mode in ("meta", "full") and used_comp_ids:
        all_meta = file_data.get("components") or {}
        if isinstance(all_meta, dict):
            meta_subset = {cid: all_meta.get(cid) for cid in used_comp_ids if cid in all_meta}
            # Drop Nones
            meta_subset = {k: v for k, v in meta_subset.items() if v is not None}
            if meta_subset:
                refs["components_meta"] = meta_subset
                # component sets (variant groups) meta, if available
                set_ids = {v.get("componentSetId") for v in meta_subset.values() if isinstance(v, dict) and v.get("componentSetId")}
                all_sets = file_data.get("componentSets") or {}
                if set_ids and isinstance(all_sets, dict):
                    sets_subset = {sid: all_sets.get(sid) for sid in set_ids if sid in all_sets}
                    sets_subset = {k: v for k, v in sets_subset.items() if v is not None}
                    if sets_subset:
                        refs["component_sets_meta"] = sets_subset

    if components_mode == "full" and used_comp_ids:
        comp_nodes = []
        for cid in used_comp_ids:
            comp_node = find_node_by_id(doc, cid)
            if isinstance(comp_node, dict) and comp_node.get("type") in ("COMPONENT", "COMPONENT_SET"):
                comp_nodes.append(comp_node)
        if comp_nodes:
            refs["component_nodes"] = comp_nodes

    if refs:
        bundle["refs"] = refs
    return bundle


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Extract only desired Figma frame(s) from saved JSON into compact JSON file(s)."
    )
    parser.add_argument("--pc-json", help="Path to saved PC JSON (fallback: env INPUT_JSON_FILE)")
    parser.add_argument("--sp-json", help="Path to saved SP JSON (fallback: env SP_INPUT_JSON_FILE)")
    parser.add_argument("--frame-id", help="Target PC frame node-id (fallback: env FRAME_NODE_ID)")
    parser.add_argument("--sp-frame-id", help="Target SP frame node-id (fallback: env SP_FRAME_NODE_ID)")
    parser.add_argument("--out-dir", default="figma_images/selected_frames", help="Output directory")
    # Default behavior: combine PC/SP into one JSON when both provided.
    # Keep --combine for backward compatibility (no-op now), and add --separate to opt out.
    parser.add_argument("--combine", action="store_true", help="[deprecated] Combine PC/SP into one JSON (now default)")
    parser.add_argument("--separate", action="store_true", help="Write PC and SP as separate files (default: combined)")
    parser.add_argument(
        "--components",
        choices=["none", "meta", "full"],
        default="meta",
        help="Include component references: none=skip, meta=top-level components meta only, full=also include COMPONENT nodes if present",
    )
    parser.add_argument(
        "--no-styles",
        action="store_true",
        help="Do not include style definitions (by default, used styles are embedded)",
    )
    parser.add_argument(
        "--chat-ready",
        action="store_true",
        help="Produce a chat-friendly compact JSON: keep essential fields, round numbers, and optionally drop vector geometries",
    )
    parser.add_argument(
        "--round-digits",
        type=int,
        default=None,
        help="When --chat-ready, round numeric values to this many digits (default: 1)",
    )
    parser.add_argument(
        "--keep-vectors",
        action="store_true",
        help="When --chat-ready, keep heavy vector geometries (default: drop)",
    )
    args = parser.parse_args()

    pc_json = args.pc_json or os.getenv("INPUT_JSON_FILE")
    sp_json = args.sp_json or os.getenv("SP_INPUT_JSON_FILE")
    frame_id = args.frame_id or os.getenv("FRAME_NODE_ID")
    sp_frame_id = args.sp_frame_id or os.getenv("SP_FRAME_NODE_ID")

    if not pc_json and not sp_json:
        raise SystemExit("No input JSON provided. Pass --pc-json/--sp-json or set INPUT_JSON_FILE/SP_INPUT_JSON_FILE in .env")

    os.makedirs(args.out_dir, exist_ok=True)

    outputs = []

    # Process PC
    pc_bundle = None
    if pc_json and frame_id:
        print(f"[LOG] Loading PC JSON: {pc_json}")
        pc_data = load_json(pc_json)
        print(f"[LOG] Extracting frame: {frame_id}")
        pc_bundle = build_frame_bundle(
            pc_data,
            frame_id,
            include_styles=(not args.no_styles),
            components_mode=args.components,
        )
        outputs.append(("pc", pc_bundle))
    elif pc_json and not frame_id:
        print("[WARN] --pc-json provided but no --frame-id or FRAME_NODE_ID. Skipping PC.")

    # Process SP
    sp_bundle = None
    if sp_json and sp_frame_id:
        print(f"[LOG] Loading SP JSON: {sp_json}")
        sp_data = load_json(sp_json)
        print(f"[LOG] Extracting frame: {sp_frame_id}")
        sp_bundle = build_frame_bundle(
            sp_data,
            sp_frame_id,
            include_styles=(not args.no_styles),
            components_mode=args.components,
        )
        outputs.append(("sp", sp_bundle))
    elif sp_json and not sp_frame_id:
        print("[WARN] --sp-json provided but no --sp-frame-id or SP_FRAME_NODE_ID. Skipping SP.")

    if not outputs:
        raise SystemExit("Nothing to output. Provide at least one of PC or SP JSON with corresponding frame id.")

    # Write files
    # Optionally post-process for chat
    def maybe_chat_prune(bundle: dict) -> dict:
        if not args.chat_ready:
            return bundle
        rd = 1 if args.round_digits is None else max(0, args.round_digits)
        return prune_bundle_for_chat(bundle, round_digits=rd, keep_vectors=args.keep_vectors)

    # Combine by default when both PC and SP are available.
    if len(outputs) == 2 and not args.separate:
        pc_b = maybe_chat_prune(pc_bundle or {})
        sp_b = maybe_chat_prune(sp_bundle or {})
        project_pc = sanitize_filename(pc_b.get("source_file_name") or "PC")
        project_sp = sanitize_filename(sp_b.get("source_file_name") or "SP")
        # Prefer a unified project name if same, else join
        if project_pc and project_sp and project_pc == project_sp:
            project = project_pc
        else:
            project = f"{project_pc or 'PC'}__{project_sp or 'SP'}"

        out_name = f"{project}__frames_pc_sp.json"
        out_path = os.path.join(args.out_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"pc": pc_b, "sp": sp_b}, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Wrote combined PC/SP frame JSON: {out_path}")
        return

    # Separate files
    for kind, bundle in outputs:
        bundle = maybe_chat_prune(bundle)
        project = sanitize_filename(bundle.get("source_file_name") or "Project")
        frame_name = sanitize_filename(bundle.get("frame_name") or kind.upper())
        node_id_safe = (bundle.get("frame_node_id") or kind).replace(":", "_")
        out_name = f"{project}__{frame_name}__{node_id_safe}__{kind}.json"
        out_path = os.path.join(args.out_dir, out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Wrote {kind.upper()} frame JSON: {out_path}")


if __name__ == "__main__":
    main()
