import os
import json
import argparse
from datetime import datetime
from urllib.parse import urlparse, parse_qs, unquote

import requests
from dotenv import load_dotenv


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


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description="Fetch Figma file JSON and save locally.")
    parser.add_argument("--pc-url", dest="pc_url", help="Figma URL for PC (extracts file key)")
    parser.add_argument("--pc-file-key", dest="pc_file_key", help="Figma file key for PC")
    parser.add_argument("--sp-url", dest="sp_url", help="Figma URL for SP (optional)")
    parser.add_argument("--sp-file-key", dest="sp_file_key", help="Figma file key for SP (optional)")
    parser.add_argument("--output-dir", dest="output_dir", default=os.getenv("OUTPUT_DIR", "figma_layout"), help="Base output directory")
    parser.add_argument("--save-latest", dest="save_latest", action="store_true", help="Also write latest_pc.json / latest_sp.json")
    args = parser.parse_args()

    token = os.getenv("FIGMA_API_TOKEN")
    if not token:
        raise SystemExit("FIGMA_API_TOKEN is required (env)")

    pc_key = args.pc_file_key
    if not pc_key and args.pc_url:
        fk, _ = parse_figma_url(args.pc_url)
        pc_key = fk
    if not pc_key:
        # fallback to env URL first (PC_FIGMA_URL or FIGMA_URL), then FILE_KEY
        pc_url_env = os.getenv("PC_FIGMA_URL") or os.getenv("FIGMA_URL")
        if pc_url_env:
            fk, _ = parse_figma_url(pc_url_env)
            pc_key = fk or pc_key
    if not pc_key:
        # finally try FILE_KEY
        pc_key = os.getenv("FILE_KEY")
    if not pc_key:
        raise SystemExit("PC file key is required (use --pc-file-key or --pc-url, or set PC_FIGMA_URL/FIGMA_URL/FILE_KEY in .env)")

    sp_key = args.sp_file_key
    if not sp_key and args.sp_url:
        fk, _ = parse_figma_url(args.sp_url)
        sp_key = fk
    if not sp_key:
        sp_url_env = os.getenv("SP_FIGMA_URL")
        if sp_url_env:
            fk, _ = parse_figma_url(sp_url_env)
            sp_key = fk or sp_key

    raw_dir = os.path.join(args.output_dir, "raw_figma_data")
    os.makedirs(raw_dir, exist_ok=True)

    # PC fetch
    pc_json = fetch_file_json(pc_key, token)
    proj = pc_json.get("name") or "Unknown_Project"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    pc_path = os.path.join(raw_dir, f"{proj}_{pc_key}_{ts}.json")
    with open(pc_path, "w", encoding="utf-8") as f:
        json.dump(pc_json, f, ensure_ascii=False, indent=2)
    print(f"[LOG] Saved PC JSON: {pc_path}")
    if args.save_latest:
        latest_pc = os.path.join(raw_dir, "latest_pc.json")
        with open(latest_pc, "w", encoding="utf-8") as f:
            json.dump(pc_json, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Updated: {latest_pc}")

    # SP fetch (optional)
    if sp_key:
        sp_json = fetch_file_json(sp_key, token)
        proj_sp = sp_json.get("name") or "Unknown_Project"
        sp_path = os.path.join(raw_dir, f"{proj_sp}_{sp_key}_{ts}_sp.json")
        with open(sp_path, "w", encoding="utf-8") as f:
            json.dump(sp_json, f, ensure_ascii=False, indent=2)
        print(f"[LOG] Saved SP JSON: {sp_path}")
        if args.save_latest:
            latest_sp = os.path.join(raw_dir, "latest_sp.json")
            with open(latest_sp, "w", encoding="utf-8") as f:
                json.dump(sp_json, f, ensure_ascii=False, indent=2)
            print(f"[LOG] Updated: {latest_sp}")


if __name__ == "__main__":
    main()
