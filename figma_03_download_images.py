import os
import re
import json
import argparse
from urllib.parse import urlparse, parse_qs, unquote

import requests
from dotenv import load_dotenv


def sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', '_', name or '')


def css_safe_identifier(text: str) -> str:
    if not text:
        return ''
    safe = re.sub(r'[^a-zA-Z0-9_-]', '-', text)
    safe = re.sub(r'-{2,}', '-', safe).strip('-')
    return safe


def parse_figma_url(url: str):
    try:
        p = urlparse(url)
        parts = [s for s in p.path.split('/') if s]
        file_key = None
        for i, seg in enumerate(parts):
            if seg in ("file", "design") and i + 1 < len(parts):
                file_key = parts[i + 1]
                break
        q = parse_qs(p.query)
        node_id = None
        for k in ("node-id", "node_id"):
            if k in q and len(q[k]) > 0:
                raw = unquote(q[k][0])
                node_id = raw
                if ':' not in node_id and '-' in node_id:
                    node_id = node_id.replace('-', ':', 1)
                break
        return file_key, node_id
    except Exception:
        return None, None


def fetch_file_json(file_key: str, token: str):
    url = f"https://api.figma.com/v1/files/{file_key}"
    headers = {"X-Figma-Token": token}
    print(f"[LOG] GET {url}")
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()


def find_node_by_id(node, target_id):
    if not isinstance(node, dict):
        return None
    if node.get("id") == target_id:
        return node
    for child in node.get("children", []) or []:
        found = find_node_by_id(child, target_id)
        if found:
            return found
    return None


def collect_image_node_ids(node):
    ids = []
    if not isinstance(node, dict):
        return ids
    fills = node.get("fills", []) or []
    for f in fills:
        if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
            nid = node.get("id")
            if nid:
                ids.append(nid)
            break
    for child in node.get("children", []) or []:
        ids.extend(collect_image_node_ids(child))
    return ids


def fetch_figma_image_urls(file_key, node_ids, image_format="png", scale=1.0, token=None):
    if not node_ids:
        return {}
    headers = {"X-Figma-Token": token} if token else {}
    ids_param = ",".join(node_ids)
    url = f"https://api.figma.com/v1/images/{file_key}?ids={ids_param}&format={image_format}&scale={scale}"
    print(f"[LOG] Requesting image URLs: {url}")
    r = requests.get(url, headers=headers)
    r.raise_for_status()
    data = r.json()
    return data.get("images", {})


def download_images(url_map, out_dir, file_ext="png", filename_suffix="", force_redownload=False):
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    for node_id, url in url_map.items():
        if not node_id or not url:
            continue
        safe_id = css_safe_identifier(node_id)
        filename = f"{safe_id}{filename_suffix}.{file_ext}"
        abs_path = os.path.join(out_dir, filename)
        if os.path.exists(abs_path) and not force_redownload:
            print(f"[CACHE] Using existing image: {abs_path}")
            saved.append(abs_path)
            continue
        try:
            resp = requests.get(url)
            resp.raise_for_status()
            with open(abs_path, "wb") as f:
                f.write(resp.content)
            print(f"[LOG] Downloaded: {abs_path}")
            saved.append(abs_path)
        except Exception as e:
            print(f"[WARN] Failed: {node_id} -> {e}")
    return saved


def resolve_file_key(cli_key, cli_url, env_key, env_url):
    if cli_key:
        return cli_key
    if cli_url:
        fk, _ = parse_figma_url(cli_url)
        if fk:
            return fk
    if env_url:
        fk, _ = parse_figma_url(env_url)
        if fk:
            return fk
    return env_key


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Download Figma images with 02-compatible naming/placement")
    parser.add_argument("--pc-json", help="Path to saved PC JSON (optional; speeds up frame search)")
    parser.add_argument("--pc-url", help="Figma PC URL (optional; to resolve FILE_KEY/node-id)")
    parser.add_argument("--pc-file-key", help="Figma PC file key (optional)")
    parser.add_argument("--frame-id", help="PC frame node-id (fallback: FRAME_NODE_ID)")

    parser.add_argument("--sp-json", help="Path to saved SP JSON (optional)")
    parser.add_argument("--sp-url", help="Figma SP URL (optional)")
    parser.add_argument("--sp-file-key", help="Figma SP file key (optional; defaults to PC key)")
    parser.add_argument("--sp-frame-id", help="SP frame node-id (fallback: SP_FRAME_NODE_ID)")

    parser.add_argument("--output-dir", default=os.getenv("OUTPUT_DIR", "figma_layout"), help="Base output directory")
    parser.add_argument("--image-format", default=os.getenv("IMAGE_FORMAT", "png"), help="Image format (png,jpg,webp,...)")
    parser.add_argument("--image-scale", default=os.getenv("IMAGE_SCALE", "1"), help="Image export scale")
    parser.add_argument("--force-redownload", action="store_true", help="Force re-download even if file exists")
    args = parser.parse_args()

    token = os.getenv("FIGMA_API_TOKEN")
    if not token:
        raise SystemExit("FIGMA_API_TOKEN is required in .env")

    # Resolve PC keys/ids
    pc_file_key = resolve_file_key(args.pc_file_key, args.pc_url, os.getenv("FILE_KEY"), os.getenv("PC_FIGMA_URL") or os.getenv("FIGMA_URL"))
    frame_id = args.frame_id or os.getenv("FRAME_NODE_ID")
    if args.pc_url and not frame_id:
        _, nid = parse_figma_url(args.pc_url)
        frame_id = frame_id or nid
    if not all([pc_file_key, frame_id]):
        raise SystemExit("PC FILE_KEY and FRAME_NODE_ID are required (via args or .env)")

    # Load file data (PC)
    if args.pc_json:
        with open(args.pc_json, "r", encoding="utf-8") as f:
            pc_file_data = json.load(f)
    else:
        pc_file_data = fetch_file_json(pc_file_key, token)

    project_name = pc_file_data.get("name", "Unknown_Project")
    safe_project_name = sanitize_filename(project_name)
    base_output_dir = os.path.join(args.output_dir, safe_project_name)
    images_dir = os.path.join(base_output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    # Find PC frame and collect image nodes
    pc_frame = find_node_by_id(pc_file_data.get("document", {}), frame_id)
    if not pc_frame:
        raise SystemExit(f"Frame not found: {frame_id}")
    image_ids = collect_image_node_ids(pc_frame)
    print(f"[LOG] PC image nodes: {len(image_ids)}")

    # Fetch URLs and download (PC)
    url_map = fetch_figma_image_urls(pc_file_key, list(set(image_ids)), args.image_format, float(args.image_scale), token)
    download_images(url_map, images_dir, args.image_format, filename_suffix="", force_redownload=args.force_redownload)

    # Optional SP
    sp_frame_id = args.sp_frame_id or os.getenv("SP_FRAME_NODE_ID")
    sp_file_key = resolve_file_key(args.sp_file_key, args.sp_url, os.getenv("SP_FILE_KEY"), os.getenv("SP_FIGMA_URL")) or pc_file_key

    if args.sp_url and not sp_frame_id:
        _, sp_nid = parse_figma_url(args.sp_url)
        sp_frame_id = sp_frame_id or sp_nid

    if sp_frame_id:
        # Load SP file data
        if args.sp_json:
            with open(args.sp_json, "r", encoding="utf-8") as f:
                sp_file_data = json.load(f)
        else:
            sp_file_data = fetch_file_json(sp_file_key, token)

        sp_frame = find_node_by_id(sp_file_data.get("document", {}), sp_frame_id)
        if not sp_frame:
            print(f"[WARN] SP frame not found: {sp_frame_id}. Skipping SP.")
        else:
            sp_image_ids = collect_image_node_ids(sp_frame)
            print(f"[LOG] SP image nodes: {len(sp_image_ids)}")
            sp_url_map = fetch_figma_image_urls(sp_file_key, list(set(sp_image_ids)), args.image_format, float(args.image_scale), token)
            download_images(sp_url_map, images_dir, args.image_format, filename_suffix="_sp", force_redownload=args.force_redownload)

    print(f"[DONE] Images saved under: {images_dir}")


if __name__ == "__main__":
    main()

