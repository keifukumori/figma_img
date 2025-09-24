## .n-（ノード固有クラス）運用メモ

このメモは、生成されたHTML/CSSに出力される `.n-<id>` クラス（ノード固有クラス）の目的/範囲/制御方法をまとめたものです。

### 目的と設計
- 目的: Figmaの各ノード（要素）を1対1でCSSにひも付け、ノード固有の見た目（背景・枠線・角丸・影・ブレンド・サイズ等）を再現する。
- プレフィックス `n-`: CSSの制約（数字始まり・コロン不可）を回避するため、Figmaのnode-id（例: `7291:125581`）を安全な識別子（例: `n-7291-125581`）に変換。
- 付与先: すべてのノード種別で付与（テキスト、コンテナ、矩形、画像、線）。

### 何が .n- に出るか（既定: conservative）
- テキスト（text）
  - `color`, `text-decoration`, `text-transform`, `font-style`, `margin`（段落間隔）
- コンテナ/矩形/画像/線（container/rect/image/line）
  - 背景（`background-color` + グラデーション `background`）
  - 枠線（`border` / 個別エッジ `border-top/right/bottom/left`）
  - 角丸（`border-radius`）
  - 影・ブラー（`box-shadow`, `filter`, `backdrop-filter`）
  - ブレンド（`mix-blend-mode`）
  - レイアウト/サイズ（`display:flex` 系、`gap/padding/overflow/height/min-height` など）
  - 重要: 非テキスト要素には `color:` を出しません（不要なカスケード防止）

### スコープ制御: `NODE_STYLE_SCOPE`
- `.env` で切替（既定: `conservative`）
  - `conservative`: 最も安全。非テキストに `color:` を出さない等、漏れ最小化。背景/枠線/角丸/影/ブレンド/高さ系/レイアウト系は許可。
  - `standard`: 非テキストの `color:` を禁止。それ以外は許可。
  - `aggressive`: 収集したプロパティをほぼ無制限で出力（検証・暫定再現用）。

### 幅の固定抑止: `SUPPRESS_CONTAINER_WIDTH`
- 既定: `true`（.envで変更可）
- 意図: コンテナに対して `width`/`min-width` を出力しない（横スクロールや張り付き崩れを防止）。
- 効果: 背景（色/グラデーション/画像）は当たるが、横幅は親の `max-width` などで柔軟に制御できる。
- 例外が必要な場合は `SUPPRESS_CONTAINER_WIDTH=false` に切替（推奨は `true`）。

### 背景の合成（重要な仕様）
- 画像fillがあるコンテナ: ラッパー `.bg-fullbleed` に多層レイヤーとして出力。
  - 最下層SOLID → `background-color`
  - グラデーション（1〜複数） → `background`
  - 画像 → `background: ..., url('...')` の最上位レイヤー
- 画像fillがないノード: `background-color` + 最上位グラデーションを出力。
- BACKGROUND_BLUR: `backdrop-filter`（+ `-webkit-backdrop-filter`）で背景ぼかしを再現。

### 典型的な崩れと対処
- 症状: 横幅が張り付く/横スクロールが出る
  - 原因: コンテナに `width/min-width` が当たっている
  - 対処: `SUPPRESS_CONTAINER_WIDTH=true`（既定）。必要なら `false` で検証 → 影響箇所のみ個別対応。
- 症状: テキストの色が意図せず白/黒になる
  - 原因: 親要素に `color:` が出てカスケード（conservative/standard では無効）
  - 対処: `NODE_STYLE_SCOPE=conservative` を推奨。`node_style_report.json` を確認。

### バリデーションレポート
- 出力先: `OUTPUT_DIR/<project>/node_style_report.json`
- 内容: `.n-` の適用状況サマリ、想定外のプロパティ（例: 非テキスト要素に `color:`）の検出。
- conservative/standard では `non_text_color` が 0 であることが期待値。

### 推奨運用
1) 既定（`NODE_STYLE_SCOPE=conservative`, `SUPPRESS_CONTAINER_WIDTH=true`）で生成。
2) レイアウト崩れがあれば `standard` に切替 → 差分確認。
3) それでも不足があれば `aggressive` で原因特定後、必要箇所のみ個別上書き or 例外追加。
4) `node_style_report.json` で“漏れ”や過剰出力を定期確認。

### よくある質問
- Q: そもそも `.n-` はなぜ必要？
  - A: Figma node-id をCSSで扱える安全な識別子にし、ノード固有の見た目を忠実に再現・上書きしやすくするためです。
- Q: `.n-` を無効化はできますか？
  - A: 可能です。ただし初期再現度が下がるため、段階的にBEM/セマンティックへ吸い上げた後に縮小する運用を推奨します。

---
更新履歴
- 2025-09: 背景の多層レイヤー適用、コンテナへの `.n-` 付与、横幅抑止・スコープ制御・レポート機能を追加。
