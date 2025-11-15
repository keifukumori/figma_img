import os
import argparse
from dotenv import load_dotenv


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Build HTML/CSS from saved Figma JSON (offline by default)")
    parser.add_argument("--pc-json", help="Path to saved PC JSON (fallback: env INPUT_JSON_FILE)")
    parser.add_argument("--sp-json", help="Path to saved SP JSON (fallback: env SP_INPUT_JSON_FILE)")
    parser.add_argument("--frame-id", help="Target PC frame node-id (fallback: env FRAME_NODE_ID)")
    parser.add_argument("--sp-frame-id", help="Target SP frame node-id (fallback: env SP_FRAME_NODE_ID)")
    parser.add_argument("--use-images", action="store_true", help="Use images if available locally (fallback: env USE_IMAGES)")
    parser.add_argument("--allow-online", action="store_true", help="Allow online access (image URLs, etc.) (fallback: env ALLOW_ONLINE=true)")
    parser.add_argument("--device-mode", choices=["pc", "sp", "both"], help="Limit build target: pc | sp | both (fallback: env DEVICE_MODE)")
    # Pipeline post steps
    parser.add_argument("--unify-styles", action="store_true", help="Post-process: unify duplicate .n-* rules into utilities and annotate HTML (fallback: env POSTPROCESS_UNIFY=true)")
    parser.add_argument("--common-utils", action="store_true", help="Post-process: inject common flex utilities and annotate HTML (fallback: env POSTPROCESS_COMMON=true)")
    parser.add_argument("--annotate-components", action="store_true", help="Post-process: annotate generic components (card / section__card) (fallback: env POSTPROCESS_COMPONENTS=true)")

    # Ops (optional, after pipeline)
    parser.add_argument("--ops-assign-sections", action="store_true", help="Ops: assign section-01/02.. to <section> lacking keys (env POST_OPS_ASSIGN_SECTIONS=true)")
    parser.add_argument("--ops-add-row-alias", action="store_true", help="Ops: add SECTION__row and extract row CSS to style-common.css (env POST_OPS_ADD_SECTION_ROW_ALIAS=true)")
    parser.add_argument("--ops-card-alias", action="store_true", help="Ops: add SECTION__card alias to elements with card (env POST_OPS_ADD_SECTION_CARD_ALIAS=true)")
    parser.add_argument("--ops-promote-shadow", action="store_true", help="Ops: promote child n-* shadow to SECTION__row-item (env POST_OPS_PROMOTE_SHADOW_TO_ROW_ITEM=true)")
    parser.add_argument("--ops-ensure-style-order", action="store_true", help="Ops: ensure style-common.css is linked after style.css (env POST_OPS_ENSURE_STYLE_ORDER=true)")
    parser.add_argument("--ops-escalate-alias-specificity", action="store_true", help="Ops: duplicate :where(.alias){..} as .alias{..} (env POST_OPS_ESCALATE_ALIAS_SPECIFICITY=true)")
    parser.add_argument("--ops-mirror-n-selectors", action="store_true", help="Ops: mirror .n-* selectors in CSS to section-scoped aliases (env POST_OPS_MIRROR_N_SELECTORS=true)")
    parser.add_argument("--ops-alias-graft", action="store_true", help="Ops: alias graft for residual n-* (append alias to HTML and comma-join CSS) (env POST_OPS_ALIAS_GRAFT=true)")
    parser.add_argument("--ops-report-n-blockers", action="store_true", help="Ops: report blockers for dropping n-* (env POST_OPS_REPORT_N_BLOCKERS=true)")
    parser.add_argument("--ops-canonicalize-bem", action="store_true", help="Ops: canonicalize BEM/alias variants (env POST_OPS_CANONICALIZE_BEM=true)")
    parser.add_argument("--ops-alias-overrides", action="store_true", help="Ops: apply alias overrides mapping (env POST_OPS_ALIAS_OVERRIDES=true)")
    parser.add_argument("--ops-alias-overrides-map", help="Path to alias overrides JSON (env POST_OPS_ALIAS_OVERRIDES_MAP)")
    # Section breaks (report/apply)
    parser.add_argument("--ops-propose-section-breaks", action="store_true", help="Ops: write section_breaks.json from HTML heuristics (env POST_OPS_PROPOSE_SECTION_BREAKS=true)")
    parser.add_argument("--ops-apply-section-breaks", action="store_true", help="Ops: apply about-01/02… from section_breaks.json (env POST_OPS_APPLY_SECTION_BREAKS=true)")
    parser.add_argument("--ops-section-break-reasons", help="Ops: reasons to pick for breaks (comma-separated). Default: heading,typography,background,rule (env POST_OPS_SECTION_BREAK_REASONS)")
    parser.add_argument("--ops-section-break-enum-width", type=int, help="Ops: enum width for about-01 (default 2). Env: POST_OPS_SECTION_BREAK_ENUM_WIDTH")
    parser.add_argument("--ops-neutralize-n-section", help="Ops: neutralize layout props in .n-* for a section key (e.g., about) (env POST_OPS_NEUTRALIZE_N_SECTION=<key>)")
    parser.add_argument("--ops-drop-n-if-covered", action="store_true", help="Ops: drop n-* from HTML when fully covered by common CSS (env POST_OPS_DROP_N_IF_COVERED=true)")
    parser.add_argument("--ops-drop-strict", action="store_true", help="Ops: use strict drop gate (no complex/media selectors) (env POST_OPS_DROP_N_STRICT=true)")
    parser.add_argument("--ops-allow-media-layout", action="store_true", help="Ops: with strict drop, allow drop for layout-only rules inside @media (env POST_OPS_ALLOW_MEDIA_LAYOUT=true)")
    parser.add_argument("--ops-allow-complex-layout", action="store_true", help="Ops: with strict drop, allow drop for layout-only complex selectors (env POST_OPS_ALLOW_COMPLEX_LAYOUT=true)")
    parser.add_argument("--ops-backup", action="store_true", help="Ops: write .bak backups when modifying files (env POST_OPS_BACKUP=true)")
    parser.add_argument("--ops-prune-unused-n-css", action="store_true", help="Ops: prune unused .n-* CSS rules/selectors after drop (env POST_OPS_PRUNE_UNUSED_N_CSS=true)")
    args = parser.parse_args()

    # Resolve inputs (CLI > env)
    pc_json = args.pc_json or os.getenv("INPUT_JSON_FILE")
    sp_json = args.sp_json or os.getenv("SP_INPUT_JSON_FILE")
    frame_id = args.frame_id or os.getenv("FRAME_NODE_ID")
    sp_frame_id = args.sp_frame_id or os.getenv("SP_FRAME_NODE_ID")
    allow_online = args.allow_online or (os.getenv("ALLOW_ONLINE", "false").lower() == "true")
    use_images = args.use_images or (os.getenv("USE_IMAGES", "false").lower() == "true")
    device_mode = args.device_mode or (os.getenv("DEVICE_MODE", "both").lower())
    post_unify = args.unify_styles or (os.getenv("POSTPROCESS_UNIFY", "false").lower() == "true")
    post_common = args.common_utils or (os.getenv("POSTPROCESS_COMMON", "false").lower() == "true")
    post_components = args.annotate_components or (os.getenv("POSTPROCESS_COMPONENTS", "false").lower() == "true")

    # Ops flags
    ops_assign = args.ops_assign_sections or (os.getenv("POST_OPS_ASSIGN_SECTIONS", "false").lower() == "true")
    ops_row_alias = args.ops_add_row_alias or (os.getenv("POST_OPS_ADD_SECTION_ROW_ALIAS", "false").lower() == "true")
    ops_card_alias = args.ops_card_alias or (os.getenv("POST_OPS_ADD_SECTION_CARD_ALIAS", "false").lower() == "true")
    ops_promote_shadow = args.ops_promote_shadow or (os.getenv("POST_OPS_PROMOTE_SHADOW_TO_ROW_ITEM", "false").lower() == "true")
    ops_style_order = args.ops_ensure_style_order or (os.getenv("POST_OPS_ENSURE_STYLE_ORDER", "false").lower() == "true")
    ops_escalate_alias = args.ops_escalate_alias_specificity or (os.getenv("POST_OPS_ESCALATE_ALIAS_SPECIFICITY", "false").lower() == "true")
    ops_mirror_selectors = args.ops_mirror_n_selectors or (os.getenv("POST_OPS_MIRROR_N_SELECTORS", "false").lower() == "true")
    ops_alias_graft = args.ops_alias_graft or (os.getenv("POST_OPS_ALIAS_GRAFT", "false").lower() == "true")
    ops_report_blockers = args.ops_report_n_blockers or (os.getenv("POST_OPS_REPORT_N_BLOCKERS", "false").lower() == "true")
    ops_canon_bem = args.ops_canonicalize_bem or (os.getenv("POST_OPS_CANONICALIZE_BEM", "false").lower() == "true")
    ops_alias_over = args.ops_alias_overrides or (os.getenv("POST_OPS_ALIAS_OVERRIDES", "false").lower() == "true")
    ops_alias_over_map = args.ops_alias_overrides_map or os.getenv("POST_OPS_ALIAS_OVERRIDES_MAP")
    ops_propose_breaks = args.ops_propose_section_breaks or (os.getenv("POST_OPS_PROPOSE_SECTION_BREAKS", "false").lower() == "true")
    ops_apply_breaks = args.ops_apply_section_breaks or (os.getenv("POST_OPS_APPLY_SECTION_BREAKS", "false").lower() == "true")
    ops_break_reasons = args.ops_section_break_reasons or os.getenv("POST_OPS_SECTION_BREAK_REASONS", "heading,typography,background,rule")
    try:
        ops_break_enum_width = int(args.ops_section_break_enum_width or (os.getenv("POST_OPS_SECTION_BREAK_ENUM_WIDTH", "2") or 2))
    except Exception:
        ops_break_enum_width = 2
    ops_neutralize_section = args.ops_neutralize_n_section or os.getenv("POST_OPS_NEUTRALIZE_N_SECTION")
    ops_drop_n = args.ops_drop_n_if_covered or (os.getenv("POST_OPS_DROP_N_IF_COVERED", "false").lower() == "true")
    ops_drop_strict = args.ops_drop_strict or (os.getenv("POST_OPS_DROP_N_STRICT", "false").lower() == "true")
    ops_allow_media_layout = args.ops_allow_media_layout or (os.getenv("POST_OPS_ALLOW_MEDIA_LAYOUT", "false").lower() == "true")
    ops_allow_complex_layout = args.ops_allow_complex_layout or (os.getenv("POST_OPS_ALLOW_COMPLEX_LAYOUT", "false").lower() == "true")
    ops_backup = args.ops_backup or (os.getenv("POST_OPS_BACKUP", "false").lower() == "true")
    ops_prune_n_css = args.ops_prune_unused_n_css or (os.getenv("POST_OPS_PRUNE_UNUSED_N_CSS", "false").lower() == "true")

    # Validate required
    if not pc_json:
        raise SystemExit("Missing PC JSON: pass --pc-json or set INPUT_JSON_FILE in .env")
    if not frame_id:
        raise SystemExit("Missing FRAME_NODE_ID: pass --frame-id or set FRAME_NODE_ID in .env")

    # Propagate to generator env only if not already set
    os.environ.setdefault("INPUT_JSON_FILE", pc_json)
    if sp_json:
        os.environ.setdefault("SP_INPUT_JSON_FILE", sp_json)
    os.environ.setdefault("FRAME_NODE_ID", frame_id)
    if sp_frame_id:
        os.environ.setdefault("SP_FRAME_NODE_ID", sp_frame_id)

    # Default to fully offline with local images only unless explicitly allowed
    if not allow_online:
        os.environ.setdefault("OFFLINE_MODE", "true")
        os.environ.setdefault("IMAGE_SOURCE", "local")

    # Control image usage
    os.environ.setdefault("USE_IMAGES", "true" if use_images else "false")

    # Device mode (pc/sp/both)
    if device_mode:
        os.environ.setdefault("DEVICE_MODE", device_mode)

    # Run the existing generator (executes at import time)
    import fetch_figma_layout  # noqa: F401

    # Optional post-processing (class consolidation + ops)
    do_any_post = any([
        post_unify, post_common, post_components,
        ops_assign, ops_row_alias, ops_card_alias, ops_promote_shadow,
        ops_style_order, ops_escalate_alias, ops_mirror_selectors, ops_alias_graft, ops_report_blockers,
        ops_propose_breaks, ops_apply_breaks, ops_canon_bem, ops_alias_over,
        bool(ops_neutralize_section), ops_drop_n,
    ])
    if do_any_post:
        import json as _json
        import re as _re
        import subprocess as _subprocess

        def _sanitize_filename(name: str) -> str:
            return _re.sub(r'[\\/\\:*?"<>|]', '_', name)

        out_dir = os.getenv("OUTPUT_DIR", "figma_layout")
        pj_name = None
        try:
            with open(pc_json, "r", encoding="utf-8") as f:
                pj = _json.load(f)
                pj_name = pj.get("name") or "Unknown_Project"
        except Exception:
            pj_name = "Unknown_Project"

        root = os.path.join(out_dir, _sanitize_filename(pj_name))
        index_html = os.path.join(root, "index.html")
        style_css = os.path.join(root, "style.css")
        if not (os.path.exists(index_html) and os.path.exists(style_css)):
            # Some configurations write combined files under the project root regardless of frame nesting
            # Attempt fallback: search for nearest index.html under OUTPUT_DIR/<project>
            for base, dirs, files in os.walk(root):
                if "index.html" in files and "style.css" in files:
                    root = base
                    index_html = os.path.join(root, "index.html")
                    style_css = os.path.join(root, "style.css")
                    break

        if os.path.exists(index_html) and os.path.exists(style_css):
            # Pipeline wrappers
            if post_unify:
                try:
                    print(f"[POST] Unify styles at: {root}")
                    _subprocess.run(["python3", "tools/pipeline/unify_styles.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[POST] unify_styles failed: {e}")
            if post_common:
                try:
                    print(f"[POST] Inject common utils at: {root}")
                    _subprocess.run(["python3", "tools/pipeline/postprocess_dedupe.py", "--root", root, "--inject-css"], check=False)
                except Exception as e:
                    print(f"[POST] postprocess_dedupe failed: {e}")
            if post_components:
                try:
                    print(f"[POST] Annotate generic components at: {root}")
                    _subprocess.run(["python3", "tools/pipeline/annotate_generic_components.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[POST] annotate_generic_components failed: {e}")

            # Ops (safe, section-scoped) — order matters
            def _maybe_backup_arg():
                return ["--backup"] if ops_backup else []

            if ops_assign:
                try:
                    print(f"[OPS] Assign section keys at: {root}")
                    _subprocess.run(["python3", "tools/ops/assign_section_keys.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] assign_section_keys failed: {e}")

            if ops_row_alias:
                try:
                    print(f"[OPS] Add section row alias at: {root}")
                    _subprocess.run(["python3", "tools/ops/add_section_row_alias.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] add_section_row_alias failed: {e}")

            if ops_card_alias:
                try:
                    print(f"[OPS] Add section card alias at: {root}")
                    _subprocess.run(["python3", "tools/ops/add_section_card_alias.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] add_section_card_alias failed: {e}")

            if ops_promote_shadow:
                try:
                    print(f"[OPS] Promote shadow to row item at: {root}")
                    _subprocess.run(["python3", "tools/ops/promote_shadow_to_row_item.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[OPS] promote_shadow_to_row_item failed: {e}")

            if ops_style_order:
                try:
                    print(f"[OPS] Ensure style-common.css order at: {root}")
                    _subprocess.run(["python3", "tools/ops/ensure_style_link_order.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] ensure_style_link_order failed: {e}")

            if ops_escalate_alias:
                try:
                    print(f"[OPS] Escalate alias specificity at: {root}")
                    _subprocess.run(["python3", "tools/ops/escalate_alias_specificity.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] escalate_alias_specificity failed: {e}")

            # Section break proposal/apply
            if ops_propose_breaks:
                try:
                    print(f"[OPS] Propose section breaks at: {root}")
                    _subprocess.run(["python3", "tools/propose_section_breaks.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[OPS] propose_section_breaks failed: {e}")

            if ops_apply_breaks:
                try:
                    print(f"[OPS] Apply section breaks at: {root}")
                    _subprocess.run(["python3", "tools/ops/apply_section_breaks.py", "--root", root, "--reasons", ops_break_reasons, "--enum-width", str(ops_break_enum_width), *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] apply_section_breaks failed: {e}")

            # Ensure aliases exist on HTML before mirroring CSS: graft first, then mirror
            if ops_alias_graft:
                try:
                    print(f"[OPS] Alias graft for residual n-* at: {root}")
                    _subprocess.run(["python3", "tools/ops/alias_graft_for_residual_n.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] alias_graft_for_residual_n failed: {e}")

            if ops_mirror_selectors:
                try:
                    print(f"[OPS] Mirror .n-* selectors to aliases at: {root}")
                    _subprocess.run(["python3", "tools/ops/mirror_n_selectors_to_alias.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] mirror_n_selectors_to_alias failed: {e}")

            if ops_canon_bem:
                try:
                    print(f"[OPS] Canonicalize BEM variants at: {root}")
                    _subprocess.run(["python3", "tools/canonicalize_bem_variants.py", "--root", root, "--backup"], check=False)
                except Exception as e:
                    print(f"[OPS] canonicalize_bem_variants failed: {e}")

            if ops_alias_over and ops_alias_over_map:
                try:
                    print(f"[OPS] Apply alias overrides at: {root}")
                    _subprocess.run(["python3", "tools/ops/alias_overrides_apply.py", "--root", root, "--map", ops_alias_over_map, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] alias_overrides_apply failed: {e}")

            if ops_report_blockers:
                try:
                    print(f"[OPS] Report n-* drop blockers at: {root}")
                    _subprocess.run(["python3", "tools/ops/report_n_drop_blockers.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[OPS] report_n_drop_blockers failed: {e}")

            if ops_neutralize_section:
                try:
                    print(f"[OPS] Neutralize n-* layout in section='{ops_neutralize_section}' at: {root}")
                    _subprocess.run(["python3", "tools/ops/neutralize_n_layout_in_section.py", "--root", root, "--section", ops_neutralize_section, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] neutralize_n_layout_in_section failed: {e}")

            if ops_drop_n:
                try:
                    print(f"[OPS] Drop n-* if covered at: {root}")
                    cmd = ["python3", "tools/ops/drop_n_if_covered.py", "--root", root]
                    if ops_drop_strict:
                        cmd.append("--strict")
                        if ops_allow_media_layout:
                            cmd.append("--allow-media-layout")
                        if ops_allow_complex_layout:
                            cmd.append("--allow-complex-layout")
                    cmd += _maybe_backup_arg()
                    _subprocess.run(cmd, check=False)
                except Exception as e:
                    print(f"[OPS] drop_n_if_covered failed: {e}")

            if ops_prune_n_css:
                try:
                    print(f"[OPS] Prune unused n-* CSS rules at: {root}")
                    _subprocess.run(["python3", "tools/ops/prune_unused_n_css_rules.py", "--root", root, *_maybe_backup_arg()], check=False)
                except Exception as e:
                    print(f"[OPS] prune_unused_n_css_rules failed: {e}")
        else:
            print(f"[POST] Skip post-processing: index.html/style.css not found under {root}")


if __name__ == "__main__":
    main()
