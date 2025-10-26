# HTML ブラッシュアップ指示テンプレート（セマンティクス/BEM/tokens + レイアウト保護）

このドキュメントは、既存のHTMLを「見た目を壊さず」にセマンティクス（nav/ul/li等）、BEM命名、tokens（CSS変数）を付与・強化する際の指示テンプレートです。崩れやすいflex/Auto Layout構造に対しては、構造変換時の“ブリッジCSS”でレイアウトを保護します。

## 目的
- 既存のHTML/CSSの見た目を維持したまま、セマンティクスとBEM/tokensを導入・強化する
- flex/Auto Layout 由来の横並びやギャップを壊さない（絶対にレイアウト崩れを出さない）

## 対象
- ファイル例: `figma_images/<Project>/index.html`
- セクション例: 見出し「<ここに見出しテキスト>」直下のカード3枚（またはN件）

## 安全原則（厳守）
- 非破壊優先: まずはrole付与やBEMクラス追加など“構造を変えない”変更から
- 構造変換は最小限: ul/li化が必要な場合のみ、対象限定で実施
- スタイル継承: 親のflex/gap/align/justify/幅は、ul/li導入後も維持
- 既存クラスは温存（追加のみ）。`.n-<id>`/既存CSSを壊さない
- 冪等性: 同じ処理を再実行しても結果が重複/破壊しない
- バックアップ作成: 変更前ファイルを `.bak`/`.brushup.bak` で必ず保存

## 実装ルール
### 1) セマンティクス（構造はそのままの時）
- リストらしい並び: 親に `role="list"`、各子に `role="listitem"`
- ナビらしい領域: 親に `role="navigation"`（不要な二重roleは禁止）

### 2) 構造変換（ul/li化）が必要な場合
- 親コンテナ直下の繰り返し要素（3件以上）だけを `<ul class="list-reset">` + `<li class="list-item-reset">` でラップ
- 既存のカードdivはliの中にそのまま残す（既存クラスや子要素は変更しない）
- BEM追記: 親（ブロック）に `__list`、子カードに `__item` を追加（既存クラスは温存）

### 3) ブリッジCSS（必須）
構造変換時は、`<head>` のtokens（`:root`）に以下を追加してからul/li化してください（レイアウト崩れ防止）。

```css
/* List reset helper for semantic lists */
:where(ul[role="list"]) { list-style: none; margin: 0; padding: 0; }
/* Bridge UL to inherit flex context from parent container */
:where(ul.list-reset) {
  list-style: none; margin: 0; padding: 0;
  display: inherit; flex-direction: inherit; justify-content: inherit; align-items: inherit; gap: inherit;
  width: 100%;
}
/* Make LI layout-transparent but keep semantics */
:where(li.list-item-reset) { display: contents; }
```

> 備考: display: contents は一部ブラウザで不安定な場合があります。必要に応じて、`li { display:block }` + 内側divを“透過”扱いするフォールバックを検討してください。

### 4) BEM/tokens
- 各 `<section>` に `data-bem-block="<block名>"` を付与
- 見出し= `block__title`、段落= `block__text`、画像ラッパ= `block__image` を追記
- inline styleの主要プロパティは `var(--token, 値)` に置換（既存見た目はfallback値で維持）。
- tokensは `<head>` に `<style id="design-tokens">` として配置

## 検出ヒューリスティック
- 「見出し『<ここ>』直下で、同じ構造/同じクラス系の要素が3件以上」ならリスト候補
- まずはrole付与だけ→崩れが無いことを確認→必要ならul/li化、の順で

## 検証（最低限）
- 変更前後で横並び/縦並びが変わっていないこと（特にPC幅、768/1024/1280）
- 画像やテキストの折返し・はみ出しが無いこと
- `role="navigation" role="list"` のような重複roleが残っていないこと

## 出力
- 対象HTMLのみを修正し、バックアップを作成
- 差分ハイライト（行番号）を提示

## ロールバック条件
- 少しでも崩れが出る場合は、構造変換（ul/li化）を撤回し、role付与（構造非変更）のみ残す

## 指示テンプレート（プロンプト）
```
目的:
- 既存のHTMLを壊さずに、セマンティクス（nav/ul/li等）とBEM/tokensを付与・強化
- レイアウト崩れ（特にflex/Auto Layout由来の横並び）を絶対に発生させない

対象:
- ファイル: figma_images/<Project>/index.html
- セクション: 「<ここに見出しテキスト>」直下のカード3枚（またはN件）

安全原則:
- 非破壊優先、構造変換は最小限、スタイル継承、既存クラス温存、冪等性、バックアップ必須

実装ルール:
1) 構造変更なし: list候補には親=role="list"、子=role="listitem"。nav候補はrole="navigation"
2) 構造変換あり: 親直下の繰り返し要素のみ<ul class="list-reset">+<li class="list-item-reset">でラップ
   - 親に__list、子に__itemのBEMを追加
   - ブリッジCSS（ul.list-reset = display:inherit + flex継承、li.list-item-reset = display:contents）をtokensに追加
3) BEM/tokens: sectionにdata-bem-block、__title/__text/__image付与、inline styleはvar(--token, 値)化

検出:
- 見出し『<ここ>』直下で同構造の要素が3件以上 → リスト候補

検証:
- 変更前後の並びに差異がない、画像のはみ出しがない、重複roleがない

出力:
- バックアップ作成 + 差分の行番号を提示

ロールバック:
- 少しでも崩れが出たらul/li化は撤回し、role付与のみ残す
```

## 例: 「美をサポートする3つのメニュー。」への適用
- 親: `<div class="... about__list">` 直下に `<ul class="list-reset about__list" role="list">`
- 子: 各カード直上に `<li class="list-item-reset" role="listitem">` を追加してカードdivを内包
- tokens（head内）にブリッジCSSを追記（上記コード）

## 参考コマンド（差分確認）
```bash
rg -n 'design-tokens|brush-up' figma_images/<Project>/index.html
rg -n '<main id="main-content"' figma_images/<Project>/index.html
rg -n 'data-bem-block' figma_images/<Project>/index.html
rg -n 'about__list|about__item|role="list"|role="listitem"' figma_images/<Project>/index.html
```

以上を“依頼メッセージ（プロンプト）”として使えば、今後も構造の意味付けとレイアウト保護を両立した修正を安全に進められます。
