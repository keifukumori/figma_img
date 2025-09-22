import os
import requests
from dotenv import load_dotenv
import json

# ---------------- 環境変数読み込み ----------------
load_dotenv()

FIGMA_API_TOKEN = os.getenv("FIGMA_API_TOKEN")
FILE_KEY = os.getenv("FILE_KEY")
FRAME_NODE_ID = os.getenv("FRAME_NODE_ID")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "figma_images")
IMAGE_FORMAT = os.getenv("IMAGE_FORMAT", "png")
IMAGE_SCALE = os.getenv("IMAGE_SCALE", "1")

if not all([FIGMA_API_TOKEN, FILE_KEY, FRAME_NODE_ID]):
    raise ValueError("APIトークン、ファイルキー、フレームIDを .env に設定してください。")

headers = {"X-Figma-Token": FIGMA_API_TOKEN}

# ---------------- ファイル情報取得 ----------------
file_url = f"https://api.figma.com/v1/files/{FILE_KEY}"
print(f"[LOG] Figma APIにアクセス: {file_url}")
resp = requests.get(file_url, headers=headers)
resp.raise_for_status()
file_data = resp.json()

# ---------------- 再帰探索関数 ----------------
def get_image_node_ids(node, path="root"):
    image_ids = []
    node_name = node.get("name", "Unnamed")
    node_type = node.get("type", "Unknown")
    print(f"[LOG] Exploring Node: {node_name} ({node_type}) at path: {path}")

    # fills がある場合をチェック
    fills = node.get("fills", [])
    if fills:
        for fill in fills:
            if fill.get("type") == "IMAGE":
                print(f"[LOG] Found image in node: {node_name} ({node['id']})")
                image_ids.append(node["id"])
                break

    # 子ノードがあれば再帰
    for i, child in enumerate(node.get("children", [])):
        child_path = f"{path}/{node_name}[{i}]"
        image_ids.extend(get_image_node_ids(child, path=child_path))

    return image_ids

# ---------------- フレームノード探索 ----------------
def find_node_by_id(node, target_id, path="root"):
    if node["id"] == target_id:
        return node
    for i, child in enumerate(node.get("children", [])):
        found = find_node_by_id(child, target_id, path=f"{path}/{node.get('name', 'Unnamed')}[{i}]")
        if found:
            return found
    return None

print(f"[LOG] Searching for Frame Node: {FRAME_NODE_ID}")
target_frame = find_node_by_id(file_data["document"], FRAME_NODE_ID)

if not target_frame:
    raise ValueError(f"フレームID {FRAME_NODE_ID} が見つかりませんでした")

print(f"[LOG] Frame found: {target_frame.get('name', 'Unnamed')}")

# ---------------- 画像ノード取得 ----------------
image_node_ids = get_image_node_ids(target_frame)
print(f"[LOG] Total image nodes found: {len(image_node_ids)}")
print(f"[LOG] Image node IDs: {image_node_ids}")

if not image_node_ids:
    print("[LOG] フレーム内に画像ノードは見つかりませんでした")
    exit()

# ---------------- 画像URL取得 ----------------
IMAGES_ENDPOINT = f"https://api.figma.com/v1/images/{FILE_KEY}"
params = {
    "ids": ",".join(image_node_ids),
    "format": IMAGE_FORMAT,
    "scale": IMAGE_SCALE
}
print(f"[LOG] Requesting image URLs from Figma API")
response = requests.get(IMAGES_ENDPOINT, headers=headers, params=params)
response.raise_for_status()
image_urls = response.json().get("images", {})
print(f"[LOG] Image URLs returned: {json.dumps(image_urls, indent=2)}")

# ---------------- 保存 ----------------
# プロジェクト名とフレーム名でサブディレクトリを作成
project_name = file_data.get("name", "Unknown_Project")
frame_name = target_frame.get("name", "Unknown_Frame")

# ディレクトリ名に使えない文字を置換
safe_project_name = project_name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_").replace("?", "_").replace("\"", "_").replace("<", "_").replace(">", "_").replace("|", "_")
safe_frame_name = frame_name.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_").replace("?", "_").replace("\"", "_").replace("<", "_").replace(">", "_").replace("|", "_")

# サブディレクトリ作成
project_dir = os.path.join(OUTPUT_DIR, safe_project_name, safe_frame_name)
os.makedirs(project_dir, exist_ok=True)
print(f"[LOG] Output directory created: {project_dir}")

for node_id, url in image_urls.items():
    if url:
        print(f"[LOG] Downloading image for node: {node_id}")
        img_data = requests.get(url).content
        # Windows対応：ファイル名の不正文字を置換
        safe_node_id = node_id.replace(":", "_").replace(";", "_")
        filename = os.path.join(project_dir, f"{safe_node_id}.{IMAGE_FORMAT}")
        with open(filename, "wb") as f:
            f.write(img_data)
        print(f"[LOG] Saved: {filename}")
    else:
        print(f"[LOG] No image URL returned for node: {node_id}")

print("[LOG] すべての画像を取得しました！")
