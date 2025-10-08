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
    parser.add_argument("--unify-styles", action="store_true", help="Post-process: unify duplicate .n-* rules into utilities and annotate HTML (fallback: env POSTPROCESS_UNIFY=true)")
    parser.add_argument("--common-utils", action="store_true", help="Post-process: inject common flex utilities and annotate HTML (fallback: env POSTPROCESS_COMMON=true)")
    parser.add_argument("--annotate-components", action="store_true", help="Post-process: annotate generic components (card / section__card) (fallback: env POSTPROCESS_COMPONENTS=true)")
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

    # Optional post-processing (class consolidation)
    if post_unify or post_common or post_components:
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
            if post_unify:
                try:
                    print(f"[POST] Unify styles at: {root}")
                    _subprocess.run(["python3", "tools/unify_styles.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[POST] unify_styles failed: {e}")
            if post_common:
                try:
                    print(f"[POST] Inject common utils at: {root}")
                    _subprocess.run(["python3", "tools/postprocess_dedupe.py", "--root", root, "--inject-css"], check=False)
                except Exception as e:
                    print(f"[POST] postprocess_dedupe failed: {e}")
            if post_components:
                try:
                    print(f"[POST] Annotate generic components at: {root}")
                    _subprocess.run(["python3", "tools/annotate_generic_components.py", "--root", root], check=False)
                except Exception as e:
                    print(f"[POST] annotate_generic_components failed: {e}")
        else:
            print(f"[POST] Skip post-processing: index.html/style.css not found under {root}")


if __name__ == "__main__":
    main()
