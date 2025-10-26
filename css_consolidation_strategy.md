# CSS統合戦略 - レスポンシブユーティリティシステム

## 1. 基本Flexユーティリティ

### 方向制御
```css
.flex-col { display: flex; flex-direction: column; }
.flex-row { display: flex; flex-direction: row; }

/* レスポンシブ: SPは縦、PCは横 */
.flex-col-to-row {
    display: flex;
    flex-direction: column;
}
@media (min-width: 768px) {
    .flex-col-to-row { flex-direction: row; }
}
```

### 整列制御
```css
.justify-start { justify-content: flex-start; }
.justify-center { justify-content: center; }
.align-start { align-items: flex-start; }
.align-center { align-items: center; }
.align-stretch { align-items: stretch; }
.self-stretch { align-self: stretch; }
```

## 2. 間隔ユーティリティ

### Gap制御
```css
.gap-6 { gap: 24px; }      /* 24px gap */
.gap-10 { gap: 40px; }     /* 40px gap */

/* レスポンシブGap */
.gap-4-md-6 { gap: 16px; }
@media (min-width: 768px) {
    .gap-4-md-6 { gap: 24px; }
}
```

### Padding制御
```css
.py-20 { padding-top: 80px; padding-bottom: 80px; }
.py-30 { padding-top: 120px; padding-bottom: 120px; }
.px-container {
    padding-left: 0;
    padding-right: 0;
    --pad-l: 420px;
    --pad-r: 420px;
}
```

## 3. コンテナユーティリティ

### 幅制御
```css
.container-full {
    width: 100%;
    align-self: stretch;
}
.container-auto {
    width: auto;
}

/* Flex shrink問題の解決 */
.flex-safe {
    min-width: 0;
}
.flex-safe.has-fixed-children {
    min-width: auto;
}
```

## 4. 背景とボーダー
```css
.bg-white { background-color: rgba(255, 255, 255, 1.00); }
.rounded-lg { border-radius: 8px; }
```

## 5. 統合例

### Before (個別クラス)
```css
.about__flex_539 {
    min-width:0;
    align-self:stretch;
    display:flex; flex-direction:column; gap:40px;
    padding:80px 420px 120px 420px; padding-left:0; padding-right:0;
    --pad-l:420px; --pad-r:420px;
    justify-content:flex-start; align-items:flex-start;
    flex-wrap:nowrap;
    width:100%;
}
```

### After (ユーティリティ組み合わせ)
```html
<div class="flex-col gap-10 py-20 px-container container-full justify-start align-start">
```

## 6. レスポンシブパターン

### PCで横並び、SPで縦並び
```html
<div class="flex-col-to-row gap-4-md-6 container-full justify-start align-center">
```

### PC大きなGap、SP小さなGap
```html
<div class="flex-col gap-6 md:gap-10">
```

## 7. 命名規則

- **モバイルファースト**: デフォルトはSP、`md:`プレフィックスでPC
- **数字は実寸基準**: gap-6 = 24px, gap-10 = 40px
- **意味的命名**: container-full, flex-safe
- **組み合わせ可能**: 複数クラスで複雑なレイアウト実現

## 8. 利点

1. **再利用性**: 同じパターンを複数箇所で使用
2. **保守性**: 1つのユーティリティを変更すれば全体に反映
3. **レスポンシブ**: 自動的にPC/SP対応
4. **可読性**: HTMLを見ればレイアウトが理解できる
5. **一貫性**: 統一されたスペーシングとパターン