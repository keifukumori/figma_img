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
    args = parser.parse_args()

    # Resolve inputs (CLI > env)
    pc_json = args.pc_json or os.getenv("INPUT_JSON_FILE")
    sp_json = args.sp_json or os.getenv("SP_INPUT_JSON_FILE")
    frame_id = args.frame_id or os.getenv("FRAME_NODE_ID")
    sp_frame_id = args.sp_frame_id or os.getenv("SP_FRAME_NODE_ID")
    allow_online = args.allow_online or (os.getenv("ALLOW_ONLINE", "false").lower() == "true")
    use_images = args.use_images or (os.getenv("USE_IMAGES", "false").lower() == "true")

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

    # Run the existing generator (executes at import time)
    import fetch_figma_layout  # noqa: F401


if __name__ == "__main__":
    main()
