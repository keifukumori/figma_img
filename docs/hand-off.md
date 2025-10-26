# Figma → HTML/CSS 自動化パイプライン ハンドオフ

本ドキュメントは、現在進行中の「Figma JSON から生成された HTML/CSS を、人間が運用・保守しやすい形に段階整流する」取り組みの要約と実行手順です。再現性・安全性（崩れ防止）を最優先に、非破壊の併記と段階削除で進めています。

## 目的と原則
- 目的: 見た目の忠実性を維持しながら、クラス列を短く・意味的に・再利用しやすく整える
- 原則:
  - 非破壊併記（:where）→ 監査 → 補完 → 段階削除（常に .bak とレポートを残す）
  - レイアウト/視覚/タイポの順で、落とさず移行
  - 自動実行可能な小ステップに分解（どの JSON にも適用可能）

## 対象ディレクトリ（サンプル）
- 対象ルート: `figma_images/TBCグループ株式会社様_Design`
  - HTML/CSS: `index.html` / `style.css`
  - バックアップ: `*.bak`（各ステップで保存）
  - レポート: `coverage_report.json` / `unused_css_report.json` / `unused_complex_css_report.json`
- ツール群: `tools/`（後処理・監査・整流スクリプト）

## ステージ（パイプライン）
以下を上から順に、小刻み・ドライラン→本適用で進めます。

1) Build（生成）
- 生成エントリ: `figma_02_build_from_json.py` → `fetch_figma_layout.py`
- 設計の要点:
  - image-text の画像カラムに clamp（固定感を緩和）
  - 固有幅のユーティリティ化（`basis-<px>`）に対応
  - `unify_styles.py`: ユーティリティに width を取り込まない（`100%`のみ許容）

2) Typography（短コード併記→正規化→バンドル化）
- 併記: `tools/annotate_typography_tokens.py`
- 正規化（重複系統/ゼロ除去）: `tools/normalize_typo_tokens.py`
- バンドル化（短い `.tx-*` に集約）: `tools/bundle_typography_tokens.py`

3) Audit → 補完 → 段階 Prune（.n- 削減）
- 監査: `tools/audit_n_class_coverage.py`
- u-* 補完: `tools/apply_u_from_coverage.py`
- 段階削除（HTML の .n-）: `tools/prune_n_classes_html.py`

4) カラム等幅（2/3/4/5/6col）の安全適用
- 2col 検出: `tools/detect_2col_candidates.py`
- 2col 適用: `tools/apply_equal_2col_by_class.py`
- Ncol 検出: `tools/detect_ncol_candidates.py`（3〜6列のカード群を保守的に検出）
- Ncol 適用: `tools/apply_equal_ncol_by_class.py`（アンカーは固有 or 安定u-* を使用）
- 等幅CSSの汎用付与: `tools/ensure_equal_ncol_css.py`
  - 例: `:where(.layout-flex-row.layout-3col-equal) > * { flex: 1 1 0; min-width: 0; }`
  - 5/6列はSPで縦積みにフォールバック（@media <=768px）

5) Visual 復元・共通化（影/角丸/罫線/背景）
- 視覚の復元: `tools/restore_visuals_from_backup.py`
- 視覚の共通化: `tools/unify_visual_aliases.py`（`.v-*` → 共有 `.vis-*`）
- カードの余白/影: `tools/annotate_card_surface_simple.py`
- 局所 padding 復元（pl/pr/pt/pb-XX）: `tools/restore_padding_from_backup.py`
- 背景グラデ復元（帯/ボタン）: `tools/restore_gradients_from_backup.py`（必要に応じて）
  - 金系/グレー系は `vis-grad-*` で復元済み。将来的に `.grad-* + theme.css`（変数）へ移行

6) CSS 整理（未使用削除）
- 単純クラス: `tools/report_unused_css.py` → `tools/prune_unused_css_simple.py`
- 複合セレクタ: `tools/report_unused_complex_css.py` →
  - 安全セット: `tools/prune_unused_complex_css.py`
  - 小バッチ: `tools/prune_unused_complex_batch.py`
- 未使用 vis/v ユーティリティ: `tools/prune_unused_vis_utils.py`
- figma-style ブリッジ削除: `tools/prune_figma_style_bridge.py`

7) 整形（可読性向上）
- クラス順序の正規化/重複除去: `tools/normalize_class_order.py`
- leaf の layout-* 誤付与をコンテナへ移動: `tools/relocate_layout_from_leaf.py`
- v-* の段階削除（`.vis-*` で完全カバー時）: `tools/prune_v_redundant_html.py`

## ここまでの進捗（TBC プロジェクト）
- .n- 削減（HTML内出現）: 554 → 0（監査→補完→段階 Prune）
- 2カラム(equal): 固有アンカーで 18 箇所に適用（非破壊）
- 視覚復元/共通化:
  - 帯/ボタンのグラデーション（`vis-grad-01/03/gold`）
  - 影/角丸/罫線の復元と共通化（`.v-*` → `.vis-*`）
  - カード余白（`.card-surface`）
- CSS 整理:
  - 単純クラス未使用: 0 まで削減
  - 複合セレクタ未使用: 段階削除を繰り返し ≈ 2 まで縮小（実害なしの残渣）
- クラス短縮:
  - タイポを `.tx-*` に 13 バンドル
  - `.v-*` を `.vis-*` がカバーした箇所から 143 箇所削除
  - クラス順序を 311 箇所で正規化
- すべてバックアップ/レポートを保存済み
  - 例: `index.html.prune_n.bak`, `style.css.prune_vis_utils.bak`, `unused_*_report.json`

## これから（優先度順）
1. v-* 完全移行の継続（`.vis-*` で 100% カバーの要素から段階削除）
2. leaf→コンテナの layout 移し替えの追加検出（あれば適用）
3. タイポ ID（`u-sign-*`）の段階削減（安全条件の拡張）
4. グラデの汎用化
   - 共通 `.grad-*`（変数参照）と `theme.css`（色バケット）の雛形を追加し、`vis-grad-*` から橋渡し → 段階移行
5. 複合セレクタ未使用の最終整理（毎回 10〜20 件単位で削除）

## 実行例（スクリプト）
ドライラン → 本適用の順で実行してください（常に .bak が作成されます）。

```
# 2カラムの検出と安全適用
python tools/detect_2col_candidates.py --root 'figma_images/…/TBCグループ株式会社様_Design'
python tools/apply_equal_2col_by_class.py --root 'figma_images/…/TBCグループ株式会社様_Design'

# 監査 → u 補完 → .n- 段階削除
python tools/audit_n_class_coverage.py --root '…' \
  && python tools/apply_u_from_coverage.py --root '…' \
  && python tools/prune_n_classes_html.py --root '…'

# 視覚復元・共通化
python tools/restore_visuals_from_backup.py --root '…'
python tools/unify_visual_aliases.py --root '…'
python tools/annotate_card_surface_simple.py --root '…'
# 必要に応じて
python tools/restore_gradients_from_backup.py --root '…'
python tools/restore_padding_from_backup.py --root '…'

# CSS の未使用削除（安全域 → 小バッチ）
python tools/report_unused_css.py --root '…' \
  && python tools/prune_unused_css_simple.py --root '…'
python tools/report_unused_complex_css.py --root '…' \
  && python tools/prune_unused_complex_css.py --root '…' \
  && python tools/prune_unused_complex_batch.py --root '…'

# v-* の段階削除（vis-* で代替できる要素のみ）
python tools/prune_v_redundant_html.py --root '…' \
  && python tools/prune_unused_vis_utils.py --root '…'

# タイポトークンのバンドル化とクラス順序の正規化
python tools/bundle_typography_tokens.py --root '…' \
  && python tools/normalize_class_order.py --root '…'
```

## 安全運用（ロールバック）
- すべてのステップは `.bak` を残します（`index.html.*.bak` / `style.css.*.bak`）。問題があれば当該 `.bak` から復元してください。
- ドライラン（`--dry-run`）で件数確認 → 本適用の順で進めると安心です。

## よくある質問 / 難所
- なぜクラスが一時的に長いのか？
  - 落とさず移行するために、ユーティリティや視覚の共通化を併記 → カバー確認 → 段階削除を行う過渡期の副作用です。
- グラデーションの完全自動名付けは難しい？
  - stop/角度/色/アルファの微差が多いため、dedupe とユーティリティ化（`.grad-*` + 変数化）までは自動、意味命名は最終レビューを推奨します。
- タイポ（`u-sign-*`）の意味名付けは？
  - まず短コード/tokens（`t-/tw-/lh-/ta-/ls-`）でカバー → 頻出セットを `.tx-*` に束ね、安定後に ID を段階的に外します。

---

本ドキュメントは、チャット切替え時の引き継ぎにも使用できます。

## パイプライン一括実行
整流ステップを順序立てて実行するヘルパーを追加しました。

- 実行: `python tools/pipeline.py --root "<対象ROOT>"`（本適用）
- ドライラン: `python tools/pipeline.py --root "<対象ROOT>" --dry-run`
- 途中止め: `--stop-on-error`
- 特定ステップのみ: `--steps unify_visual_aliases prune_v_redundant_html normalize_class_order`

実行後、要約は `<ROOT>/pipeline_summary.json` に出力されます。各ステップは冪等で `.bak` を残す構成です。

---

## セッション要約（2025-10-04 時点）

このプロジェクト（figma_img）は「Figma のデザイン（JSON/オフライン）を安定した HTML/CSS に変換し、その後の人手運用をしやすく段階整流する」ためのツール群とパイプラインの集合です。生成結果はどのファイルにも適用できる汎用ロジックを目指し、崩れ防止を最優先に「併記→監査→補完→段階削除」で進めます。

- 目的と原則（要約）
  - 見た目を崩さず、クラス列を短く・意味的に・再利用しやすくする。
  - どの入力でも再現できる保守的ロジック（ヒューリスティクスは安全側）。
  - 常に `.bak` を残し、ドライラン→本適用の二段構え。

- このセッションでの主な整流
  - v→vis 共通化と段階削除（メインの v-* は 0 まで削減）。
  - .n-* 監査→u/tx 補完→段階削除（メインは 0）。
  - タイポの短縮・整合（annotate/normalize/bundle に加え、JSON基準で weight/size/align を tx-*/t-* に整合）。
  - 旧ブリッジ（men-s-tbc/text-size-*/figma-style-*/tw/lhr/ta）の除去（tx-* を持つ要素のみ安全削除）。
  - 2col(equal) と Ncol(3/4/5/6) の等幅化（親に `layout-{N}col(-equal)` を付与）と汎用CSSユーティリティ追加。
  - 未使用CSS（単純/複合）の段階削除（サブ出力含め 0 まで圧縮）。

- 最終合意の「間隔」ポリシー（シンプル版、運用前提）
  - テキスト（見出し/本文/注釈）: intrinsic margin は 0、隣接マージン（role-* 同士）で制御。
  - ブロック（layout-*/card-surface/bg-fullbleed 等）: 親の gap（u-c-gNN; Figmaの itemSpacing）で制御。
  - それ以外の自動マージン付与（JSON距離/一括フォールバック）は撤回（複雑化・誤判定を回避し運用で担保）。
  - 運用上は「セクション親を縦Auto Layout＋itemSpacing設定（= u-c-gNN を出す）」を推奨。

## 現在の状態（2025-10-04）

- メイン（`figma_images/TBCグループ株式会社様_Design`）
  - `.n-*` = 0（完了）
  - `.v-*` = 0（完了）
  - 未使用CSS（単純/複合）= 0（完了）
  - タイポは `tx-*`/`t-*` へ統一整流済み。必要最小限の `u-sign-*` は一部残る場合あり（崩れ防止）。

- サブ出力（PC/SP）
  - 未使用CSS（単純/複合）= 0（完了）
  - `.n-*` 残（監査上 needs_keep のため据え置き）
    - PC: 40 / SP: 28
  - 2col/Ncol 等幅化と視覚整理は反映済み。

## 次にやると良い作業（推奨順）

1. メインの `u-sign-*` の段階削減（任意）
   - CSS に実体がない（style.css に :where(.u-sign-xxxx) が無い）ものを HTML から安全削除。
   - ツール: `tools/prune_u_sign_safe.py --root <ROOT>`（dry-run→適用）

2. サブの `.n-*` 追加削減（小バッチ）
   - ツール: `audit_n_class_coverage.py` → `apply_u_from_coverage.py` → `prune_n_classes_html.py`
   - ドライラン→適用を数回に分けて実施（崩れが無いことを確認）。

3. 表示の微調整（必要時のみ）
   - テキスト間（role-* 同士）は `ensure_gap_margin_consistency.py` と `normalize_class_order.py` の適用で安定。
   - ブロック間は「親の gap（u-c-gNN）」がないと間が入らないので、Figma 側で縦Auto Layout＋itemSpacing を推奨。

## 使い方（最小コマンド）

- 一括（安全・冪等）
  - `python tools/pipeline.py --root "<対象ROOT>" --dry-run`
  - `python tools/pipeline.py --root "<対象ROOT>"`

- 主な個別ツール
  - 視覚整理: `unify_visual_aliases.py` / `prune_v_redundant_html.py`
  - `.n-*` 監査～削除: `audit_n_class_coverage.py` → `apply_u_from_coverage.py` → `prune_n_classes_html.py`
  - タイポ短縮: `annotate_typography_tokens.py` → `normalize_typo_tokens.py` → `bundle_typography_tokens.py`
  - 2col/Ncol 等幅: `detect_2col_candidates.py` / `apply_equal_2col_by_class.py` / `detect_ncol_candidates.py` / `apply_equal_ncol_by_class.py`
  - 未使用CSS: `report_unused_css.py` / `report_unused_complex_css.py` → `prune_unused_css_simple.py` / `prune_unused_complex_batch.py`
  - クラス順序: `normalize_class_order.py`

- 安全運用
  - すべてのツールは `.bak` を残します（`index.html.*.bak` / `style.css.*.bak`）。
  - まず `--dry-run` で件数確認→問題なければ適用の順で進めてください。

## よくある質問（今回の論点）

- u-sign-xxxx とは？
  - `.n-*` 削除時の崩れ防止のために併記された最小ユーティリティ（例: `align-self:stretch`）。CSSで実体が無いものは冗長なので段階削除可。

- ブロック間のマージンはどう入る？
  - 親の gap（u-c-gNN; Figma の itemSpacing）を使います。親に gap が無い場合は自動付与しません（誤判定回避のため）。
  - 運用として「セクション親を縦Auto Layout＋itemSpacing設定」にすることを推奨します。

- JSON距離を使った自動マージンは？
  - 複雑化・誤判定リスクが高く、最終的に撤回しました。必要な箇所だけ局所で（Figma 側の設定で）担保してください。

## 新しいチャットへの引き継ぎ要点（TL;DR）

- 目的: Figma→HTML/CSS の自動生成物を、どの案件にも適用できる汎用ロジックで整流し、人手運用を楽にする。
- 方針: 併記→監査→補完→段階削除。崩さない。`.bak` と `--dry-run` 必須。
- 間隔: テキスト＝隣接margin／ブロック＝親gap（u-c-gNN）。このルールに一本化。
- 現状: メインは v=0,n=0,未使用CSS=0。サブは未使用CSS=0、`.n-*` が PC:40 / SP:28 残。
- 次手: `u-sign-*` の段階削除（メイン）、`.n-*` の追加削減（サブ）、必要に応じて微調整。
