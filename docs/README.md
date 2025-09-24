# Figma レイアウト自動生成 ツール ドキュメント

このリポジトリは、Figma のデザインから静的な HTML/CSS（必要に応じて画像）を自動生成するためのスクリプト群です。開発サイクルを効率化するため、オンライン取得（API）とオフライン生成を分離した 2 段階ワークフローをサポートしています。

## 構成
- `figma_01_fetch_json.py` … Figma API からファイル JSON（PC/任意でSP）を取得して保存する取得専用スクリプト
- `figma_02_build_from_json.py` … 保存済み JSON から HTML/CSS を生成するビルド専用スクリプト（デフォルト完全オフライン）
- `fetch_figma_layout.py` … 生成スクリプト（従来型）。環境変数 `INPUT_JSON_FILE` を指定すれば API なしで生成可能

出力先（既定）: `figma_layout/<プロジェクト>/` 以下に HTML/CSS、`figma_layout/images/` に画像、`figma_layout/raw_figma_data/` に JSON を保存します（`OUTPUT_DIR` で変更可能）。

## セットアップ
```bash
pip install -r requirements.txt
```

`.env` を用意（例は `docs/.env.example` 参照）。オンライン取得を行う場合は少なくとも `FIGMA_API_TOKEN` が必要です。

## 推奨ワークフロー（2段階）

### 1) 取得（初回のみ）
Figma API から JSON を保存します。必要なら画像ダウンロードは生成時に行います。

例（PC のみ保存・latest を作成）
```bash
python figma_01_fetch_json.py \
  --pc-url "https://www.figma.com/file/<FILE_KEY>?node-id=1%3A2" \
  --output-dir figma_layout \
  --save-latest
```

SP も保存する場合
```bash
python figma_01_fetch_json.py \
  --pc-url "https://www.figma.com/file/<FILE_KEY_PC>?node-id=1%3A2" \
  --sp-url "https://www.figma.com/file/<FILE_KEY_SP>?node-id=3%3A4" \
  --output-dir figma_layout \
  --save-latest
```

保存先:
- JSON: `OUTPUT_DIR/raw_figma_data/<Project>_<FILE_KEY>_<timestamp>.json`
- 直近参照: `OUTPUT_DIR/raw_figma_data/latest_pc.json`（SP は `latest_sp.json`）

### 2) 生成（以後はオフラインで高速反復）

推奨: ビルド専用スクリプトを使用（デフォルトで完全オフライン・ローカル画像のみ）
```bash
# .env に以下を記載しておけば引数なしで実行可能
# INPUT_JSON_FILE=figma_layout/raw_figma_data/latest_pc.json
# FRAME_NODE_ID=1:2
# USE_IMAGES=true
python figma_02_build_from_json.py
```

PC + SP の生成
```bash
# .env 例
# INPUT_JSON_FILE=figma_layout/raw_figma_data/latest_pc.json
# SP_INPUT_JSON_FILE=figma_layout/raw_figma_data/latest_sp.json
# FRAME_NODE_ID=1:2
# SP_FRAME_NODE_ID=3:4
# USE_IMAGES=true
python figma_02_build_from_json.py
```

オンライン（画像 CDN 参照など）を許可する場合
```bash
# .env に ALLOW_ONLINE=true を追加すれば許可可能
# 例: ALLOW_ONLINE=true
python figma_02_build_from_json.py
```

従来スクリプトを直接使う（オフライン）の例
```bash
INPUT_JSON_FILE=figma_layout/raw_figma_data/latest_pc.json \
FRAME_NODE_ID=1:2 \
OFFLINE_MODE=true IMAGE_SOURCE=local USE_IMAGES=true \
python fetch_figma_layout.py
```

## 主な環境変数（抜粋）

コア
- `FIGMA_API_TOKEN` … Figma API トークン（取得時に必要）
- `FILE_KEY` / `FRAME_NODE_ID` … 取得・生成対象（`INPUT_JSON_FILE` 利用時は `FRAME_NODE_ID` のみ必須）
- `OUTPUT_DIR` … 出力ルート（既定: `figma_layout`）

オフライン入力
- `INPUT_JSON_FILE` / `SP_INPUT_JSON_FILE` … ローカル JSON 指定で API を回避
- `OFFLINE_MODE` … `true` で全 HTTP アクセス抑止
- `IMAGE_SOURCE` … `local` で画像もローカルのみ参照（`auto` で状況に応じて URL/ローカル）

画像
 - `USE_IMAGES` … 画像を HTML に適用するか（既定: false）
  - `DOWNLOAD_IMAGES` … URL 取得時にローカルへ保存（既定: true）
  - `IMAGE_FORMAT` / `IMAGE_SCALE` … 画像エクスポート設定
  - `NODE_STYLE_SCOPE` … `.n-<id>` の出力強度（`conservative`|`standard`|`aggressive`、既定: conservative）
    - conservative: 非テキスト要素に `color:` を出さない等、漏れを最小化
    - standard: 非テキスト要素の `color:` を禁止、それ以外は許容
    - aggressive: 収集プロパティをほぼ無制限で出力
  - `SUPPRESS_CONTAINER_WIDTH` … コンテナ要素の `width`/`min-width` を抑制（既定: true）
  - `SUPPRESS_FIXED_HEIGHT` … 画像/矩形等の固定 `height` を抑制（既定: true）
  - `USE_ASPECT_RATIO` … 固定高さの代わりに `aspect-ratio` を付与（既定: true）
  - `HPAD_MODE` … 大きい左右パディングの正規化（`none`|`trim`|`clamp`、既定: none）
    - `trim`: 左右がほぼ対称かつ閾値以上なら `padding-left/right:0` に上書き
    - `clamp`: `padding-left/right: clamp(min, vw, original)` に置換
  - `HPAD_SCOPE` … 正規化の適用範囲（`none`|`all`|`wrapper_only`、既定: wrapper_only）
    - wrapper_only: ラッパーらしいFRAME（幅がルートの90%以上、左右ほぼ対称、もしくはルート直下の子）にのみ適用
    - all: すべてのAuto Layoutコンテナに適用
    - none: 適用しない
  - `HPAD_WRAPPER_MIN_WIDTH_RATIO` … ラッパー判定の最小幅比（既定: 0.9）
  - `EQUALIZE_2COL_FALLBACK` … 比率クラスが無い2カラムを等分にするフォールバック（既定: true）
  - `DETECT_EQUAL_2COL` … 自動検出での `layout-2col-equal` 付与（既定: true）
  - `STOP_CHILD_EQUALIZE` … 子要素への既定 `flex:1…` 付与を停止（既定: true）
  - `USE_ABB_RATIO_2COL` … 2カラムで子2つの `absoluteBoundingBox.width` から比率を算出し、各子に `flex-basis:%` を付与（既定: true）
  - `USE_AL_RATIO_2COL` … 2カラムでAuto Layout配分（FIXED/FILL/HUG, layoutGrow, gap, padding）から子の幅を算出して適用（既定: true、ABB比率より優先）
  - `HPAD_TRIM_MIN_PX` … `trim`時の左右パディング閾値（既定: 100）
  - `HPAD_SYMM_TOL_PX` … 左右対称判定の許容差（既定: 16）
  - `HPAD_CLAMP_MIN_PX` … `clamp`時の最小px（既定: 16）
  - `HPAD_CLAMP_VW` … `clamp`時の中間値vw（既定: 5）

除外/共通部品検出
- `EXCLUDE_LAYER_NAMES` / `EXCLUDE_LAYER_IDS`
- `EXCLUDE_HEADER_FOOTER`
- `EXCLUDE_INCLUDES`, `INCLUDE_*` … Include ライク（共通部品）自動判定の挙動

出力形態
- `SINGLE_HTML` … index.html/style.css の結合出力を作成（既定: true）
- `SINGLE_HTML_ONLY` … フレームごとの個別 HTML/CSS をスキップ（既定: true）

その他（抜粋）
- `SAVE_RAW_DATA` … 解析時に JSON を保存（`raw_figma_data/`）
- `PC_STRICT_CLAMP` … 横スクロール抑止の強制幅制約（PC）

## 出力物の場所
- JSON: `OUTPUT_DIR/raw_figma_data/`
- 画像: `OUTPUT_DIR/<project>/images/`（結合時は `OUTPUT_DIR/images/` を共有）
- HTML/CSS: `OUTPUT_DIR/<project>/...` または `OUTPUT_DIR/<project>/index.html` + `style.css`
 - レポート: `OUTPUT_DIR/<project>/node_style_report.json`（.n-クラスの適用状況チェック）

## トラブルシュート（よくある質問）
- 生成だけしたいが API を叩きたくない
  - `INPUT_JSON_FILE` と `FRAME_NODE_ID` を指定。完全に API を抑止したい場合は `OFFLINE_MODE=true` か `IMAGE_SOURCE=local` も併用。
- 画像が表示されない
  - ローカル画像未保存のときはプレースホルダーになります。取得時にダウンロードするか（`DOWNLOAD_IMAGES=true`）、`--allow-online` で URL を許可してください。
- SP だけオフライン生成したい
  - `SP_INPUT_JSON_FILE` と `SP_FRAME_NODE_ID` を指定。JSON がない場合は SP 解析はスキップされます。

---
詳細な機能・想定精度などは `docs/requirements.md` を参照してください。
