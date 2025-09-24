import os
import re
import json
import argparse
from urllib.parse import urlparse, parse_qs, unquote

import requests
from dotenv import load_dotenv
try:
    from PIL import Image
except Exception:
    Image = None


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


def collect_image_fill_refs(node):
    """Return list of imageRef strings for visible IMAGE fills within this node (no recursion)."""
    refs = []
    fills = node.get("fills", []) or []
    for f in fills:
        if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
            ref = f.get("imageRef") or f.get("imageRefHash") or f.get("imageHash")
            if ref:
                refs.append(ref)
    return refs


def fetch_file_imagefill_urls(file_key, image_refs, token=None, image_format="png", scale=1.0):
    """Resolve imageRef (hash) -> URL using File Images API (no compositing)."""
    if not image_refs:
        return {}
    headers = {"X-Figma-Token": token} if token else {}
    ids_param = ",".join(sorted(set(image_refs)))
    url = (
        f"https://api.figma.com/v1/files/{file_key}/images?"
        f"ids={ids_param}&format={image_format}&scale={scale}"
    )
    print(f"[LOG] Resolving image fills: {url}")
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


def save_processed_fill_image(img_bytes, out_path, mode, target_w, target_h, file_ext="png"):
    if Image is None:
        # Fallback: save raw bytes
        with open(out_path, "wb") as f:
            f.write(img_bytes)
        return
    from io import BytesIO
    try:
        src = Image.open(BytesIO(img_bytes)).convert("RGBA")
        tw, th = int(round(target_w)), int(round(target_h))
        if tw <= 0 or th <= 0:
            # Save original if invalid size
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            return

        mode = (mode or "FILL").upper()
        if mode == "FILL":
            # cover: scale to cover, then center-crop
            s = max(tw / src.width, th / src.height)
            new_w, new_h = int(round(src.width * s)), int(round(src.height * s))
            img = src.resize((new_w, new_h), Image.LANCZOS)
            left = max(0, (new_w - tw) // 2)
            top = max(0, (new_h - th) // 2)
            img = img.crop((left, top, left + tw, top + th))
        elif mode == "FIT":
            # contain: scale to fit, center with transparent letterbox
            s = min(tw / src.width, th / src.height)
            new_w, new_h = int(round(src.width * s)), int(round(src.height * s))
            resized = src.resize((new_w, new_h), Image.LANCZOS)
            img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            left = (tw - new_w) // 2
            top = (th - new_h) // 2
            img.paste(resized, (left, top), resized)
        elif mode == "TILE":
            # simple tile at 100%
            tile = src
            img = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
            y = 0
            while y < th:
                x = 0
                while x < tw:
                    img.paste(tile, (x, y), tile)
                    x += tile.width
                y += tile.height
        elif mode == "STRETCH":
            img = src.resize((tw, th), Image.LANCZOS)
        else:
            # default to cover
            s = max(tw / src.width, th / src.height)
            new_w, new_h = int(round(src.width * s)), int(round(src.height * s))
            img = src.resize((new_w, new_h), Image.LANCZOS)
            left = max(0, (new_w - tw) // 2)
            top = max(0, (new_h - th) // 2)
            img = img.crop((left, top, left + tw, top + th))

        # Convert mode for JPEG
        ext = (os.path.splitext(out_path)[1][1:] or file_ext).lower()
        if ext in ("jpg", "jpeg") and img.mode == "RGBA":
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        img.save(out_path)
    except Exception:
        with open(out_path, "wb") as f:
            f.write(img_bytes)


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
    parser.add_argument("--ref-only", action="store_true", help="Do not fallback to node render (avoid text compositing)")
    parser.add_argument("--leaf-only", action="store_true", help="Target only leaf nodes (no children) with IMAGE fills")
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
    # Collect target nodes
    if args.leaf_only:
        def collect_leaf_image_nodes(n):
            ids = []
            if not isinstance(n, dict):
                return ids
            if not n.get("children"):
                fills = n.get("fills", []) or []
                for f in fills:
                    if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                        nid = n.get("id")
                        if nid:
                            ids.append(nid)
                        break
            for c in n.get("children", []) or []:
                ids.extend(collect_leaf_image_nodes(c))
            return ids
        image_ids = collect_leaf_image_nodes(pc_frame)
    else:
        image_ids = collect_image_node_ids(pc_frame)
    print(f"[LOG] PC image nodes: {len(image_ids)}")

    # Prefer fill imageRef (no text compositing). Fallback to node render per-node if missing.
    # Build node_id -> primary imageRef mapping and fill info
    node_to_ref = {}
    node_fill_info = {}  # nid -> { 'scaleMode': str, 'bounds': (w,h) }
    all_refs = []
    def walk(node):
        if not isinstance(node, dict):
            return
        nid = node.get("id")
        if nid:
            fills = node.get("fills", []) or []
            # primary IMAGE fill only
            for f in fills:
                if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                    ref = f.get("imageRef") or f.get("imageRefHash") or f.get("imageHash")
                    if ref:
                        node_to_ref[nid] = ref
                        all_refs.append(ref)
                        node_fill_info[nid] = {
                            'scaleMode': f.get('scaleMode', 'FILL'),
                            'bounds': (
                                float((node.get('absoluteBoundingBox') or {}).get('width') or 0),
                                float((node.get('absoluteBoundingBox') or {}).get('height') or 0)
                            )
                        }
                    break
        for c in node.get("children", []) or []:
            walk(c)
    walk(pc_frame)

    # Resolve imageRef -> URL
    unique_refs = sorted(set(all_refs))
    print(f"[LOG] imageRef collected: {len(unique_refs)} (from nodes: {len(node_to_ref)})")
    ref_url_map = fetch_file_imagefill_urls(
        pc_file_key, unique_refs, token, args.image_format, float(args.image_scale)
    )

    # Prepare final URL map per node (fallback to node render when ref missing)
    final_url_map = {}
    fallback_nodes = []
    for nid in image_ids:
        ref = node_to_ref.get(nid)
        if ref and ref_url_map.get(ref):
            # We'll process these with PIL to match container size/scaleMode
            pass
        else:
            fallback_nodes.append(nid)

    if fallback_nodes and not args.ref_only:
        print(f"[LOG] Fallback to node render for {len(fallback_nodes)} nodes")
        node_url_map = fetch_figma_image_urls(pc_file_key, list(set(fallback_nodes)), args.image_format, float(args.image_scale), token)
        final_url_map.update({nid: url for nid, url in node_url_map.items() if url})
    elif fallback_nodes and args.ref_only:
        print(f"[LOG] Ref-only mode: skip {len(fallback_nodes)} nodes without resolvable imageRef")

    print(f"[LOG] Final PC images to download: {len(final_url_map)}")

    # Process ref-based images
    processed_count = 0
    for nid in image_ids:
        ref = node_to_ref.get(nid)
        url = ref_url_map.get(ref) if ref else None
        if not url:
            continue
        info = node_fill_info.get(nid, {})
        mode = info.get('scaleMode', 'FILL')
        w, h = info.get('bounds', (0, 0))
        tw = float(w) * float(args.image_scale)
        th = float(h) * float(args.image_scale)
        safe_id = css_safe_identifier(nid)
        out_path = os.path.join(images_dir, f"{safe_id}.{args.image_format}")
        if os.path.exists(out_path) and not args.force_redownload:
            print(f"[CACHE] Using existing image: {out_path}")
            processed_count += 1
            continue
        try:
            r = requests.get(url)
            r.raise_for_status()
            save_processed_fill_image(r.content, out_path, mode, tw, th, args.image_format)
            print(f"[LOG] Saved (processed): {out_path} [{mode} {int(tw)}x{int(th)}]")
            processed_count += 1
        except Exception as e:
            print(f"[WARN] Failed to process ref image for {nid}: {e}")

    print(f"[LOG] Processed ref-based images: {processed_count}")

    # Download fallback node renders (may include text unless --ref-only)
    download_images(final_url_map, images_dir, args.image_format, filename_suffix="", force_redownload=args.force_redownload)

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
            if args.leaf_only:
                def collect_leaf_image_nodes_sp(n):
                    ids = []
                    if not isinstance(n, dict):
                        return ids
                    if not n.get("children"):
                        fills = n.get("fills", []) or []
                        for f in fills:
                            if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                                nid = n.get("id")
                                if nid:
                                    ids.append(nid)
                                break
                    for c in n.get("children", []) or []:
                        ids.extend(collect_leaf_image_nodes_sp(c))
                    return ids
                sp_image_ids = collect_leaf_image_nodes_sp(sp_frame)
            else:
                sp_image_ids = collect_image_node_ids(sp_frame)
            print(f"[LOG] SP image nodes: {len(sp_image_ids)}")

            # SP: prefer fill imageRef as well
            sp_node_to_ref = {}
            sp_node_fill_info = {}
            sp_all_refs = []
            def walk_sp(n):
                if not isinstance(n, dict):
                    return
                nid = n.get("id")
                if nid:
                    fills = n.get("fills", []) or []
                    for f in fills:
                        if isinstance(f, dict) and f.get("type") == "IMAGE" and f.get("visible", True):
                            ref = f.get("imageRef") or f.get("imageRefHash") or f.get("imageHash")
                            if ref:
                                sp_node_to_ref[nid] = ref
                                sp_all_refs.append(ref)
                                sp_node_fill_info[nid] = {
                                    'scaleMode': f.get('scaleMode', 'FILL'),
                                    'bounds': (
                                        float((n.get('absoluteBoundingBox') or {}).get('width') or 0),
                                        float((n.get('absoluteBoundingBox') or {}).get('height') or 0)
                                    )
                                }
                            break
                for c in n.get("children", []) or []:
                    walk_sp(c)
            walk_sp(sp_frame)

            sp_ref_url_map = fetch_file_imagefill_urls(
                sp_file_key, sp_all_refs, token, args.image_format, float(args.image_scale)
            )
            sp_final_url_map = {}
            sp_fallback_nodes = []
            for nid in sp_image_ids:
                ref = sp_node_to_ref.get(nid)
                if ref and sp_ref_url_map.get(ref):
                    pass
                else:
                    sp_fallback_nodes.append(nid)

            if sp_fallback_nodes and not args.ref_only:
                print(f"[LOG] SP fallback to node render for {len(sp_fallback_nodes)} nodes")
                sp_node_url_map = fetch_figma_image_urls(sp_file_key, list(set(sp_fallback_nodes)), args.image_format, float(args.image_scale), token)
                sp_final_url_map.update({nid: url for nid, url in sp_node_url_map.items() if url})
            elif sp_fallback_nodes and args.ref_only:
                print(f"[LOG] SP ref-only mode: skip {len(sp_fallback_nodes)} nodes without resolvable imageRef")

            print(f"[LOG] Final SP images to download: {len(sp_final_url_map)}")
            # Process SP ref-based
            sp_processed = 0
            for nid in sp_image_ids:
                ref = sp_node_to_ref.get(nid)
                url = sp_ref_url_map.get(ref) if ref else None
                if not url:
                    continue
                info = sp_node_fill_info.get(nid, {})
                mode = info.get('scaleMode', 'FILL')
                w, h = info.get('bounds', (0, 0))
                tw = float(w) * float(args.image_scale)
                th = float(h) * float(args.image_scale)
                safe_id = css_safe_identifier(nid)
                out_path = os.path.join(images_dir, f"{safe_id}_sp.{args.image_format}")
                if os.path.exists(out_path) and not args.force_redownload:
                    print(f"[CACHE] Using existing image: {out_path}")
                    sp_processed += 1
                    continue
                try:
                    r = requests.get(url)
                    r.raise_for_status()
                    save_processed_fill_image(r.content, out_path, mode, tw, th, args.image_format)
                    print(f"[LOG] Saved (processed SP): {out_path} [{mode} {int(tw)}x{int(th)}]")
                    sp_processed += 1
                except Exception as e:
                    print(f"[WARN] Failed to process SP ref image for {nid}: {e}")

            print(f"[LOG] Processed SP ref-based images: {sp_processed}")

            # Download SP fallback
            download_images(sp_final_url_map, images_dir, args.image_format, filename_suffix="_sp", force_redownload=args.force_redownload)

    print(f"[DONE] Images saved under: {images_dir}")


if __name__ == "__main__":
    main()
