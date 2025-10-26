# Class Consolidation – Current State and Next Steps

This document summarizes what we implemented so far to consolidate “similar classes into one shared component,” and what we will do next to make it robust across projects (other Figma files) while preserving layout and visual intent safely.

## Goals

- Human‑readable class structure: move common styling into a shared base, leave only minimal, meaningful differences as modifiers.
- Project‑agnostic pipeline: same consolidation logic runs on any generated project root.
- Safety first: never break layout; prefer opt‑in switches for destructive actions (e.g., dropping n‑classes).

## What’s Implemented

### 1) Equal‑width rows (layout‑driven)

- Added an explicit equalize trigger `eq-cols` with CSS:
  - `:where(.eq-cols) > * { flex: 1 1 0; min-width: 0 }`
  - This does not depend on visual card detection and works purely from layout.
- Post‑process heuristic to add `eq-cols` to `fx-row` parents with 2–4 direct children (no fixed widths), and to ensure `min-w-0` on children.
- Normalization under `eq-cols`:
  - Enforce `ai-stretch` on the parent, remove redundant child `h-full/h-auto` and `as-*`.
  - Neutralize stray child heights in CSS (context‑bound, not globally).

### 2) Shared base class for siblings

- Compute the intersection of utility tokens across equalized siblings (after 4px‑grid quantization) and promote that intersection into a base class:
  - Generic base: `.row-item`
  - Section‑scoped base: `about__row-item` (first section class name + `__row-item`)
- Replace covered tokens on each child with the base class; leave only deltas (e.g., `jc-*`) on the element.
- Differences in `justify-content` are mapped to derived modifiers (leading `__`), e.g.:
  - `__center`, `__end`, `__between`
  - These are additive and do not fight the base.

Notes
- Visual promotion (background/shadow/radius) was implemented but is now conservative/opt‑in due to risk of over‑applying visuals. The default pipeline keeps visuals local unless all members clearly match.

### 3) Global consolidation within a section

- New tool: `tools/global_consolidate_components.py`
  - Scans the entire project; groups `n-*` classes by (section, normalized base signature) and emits a section‑scoped base alias (e.g., `about__row-item`).
  - Appends the base alias to matching HTML nodes. This is not a delete, it’s consolidation (single source of truth).

### 4) Safe dropping of `n-*` (opt‑in)

- `DROP_N_IF_COVERED=true`: enables the final pass that removes `n-*` from HTML only when fully covered by utilities/BEM/style‑common.css.
- Coverage now includes both `style.css` and `style-common.css` (and supports `:where(.class)` syntax).
- Default remains off (`false`) to keep `n-*` as fallback.

### 5) Pipeline wrapper (project‑agnostic)

- New wrapper: `tools/apply_project_optimizations.py`
  - Runs the safe post‑processing sequence for any generated project root.
  - Backups are written (e.g., `.bak`), so changes are reversible.
  - Integrates section‑wide consolidation via `tools/global_consolidate_components.py` and emits a residuals report.

### 6) New safety switches and diagnostics

- Visual promotion is now opt‑in:
  - Pass `--promote-visuals` to `tools/postprocess_dedupe.py`, or `PROMOTE_VISUALS=true` env, to promote identical background/shadow/radius into `.row-item`.
- Non‑eq row consolidation is opt‑in:
  - Pass `--consolidate-non-eq` (or `CONSOLIDATE_NON_EQ=true`) to consolidate common layout/spacing tokens across `fx-row` siblings even without `eq-cols`.
- Span modifiers available in CSS:
  - `:where(.eq-cols)>*.__span-2{flex:2 1 0}`, `:where(.eq-cols)>*.__span-3{flex:3 1 0}`.
- Residuals report:
  - `tools/report_residuals.py --root <Project> --visuals` writes `residuals.json` showing which props block safe `n-*` drops; prints common‑visuals candidates per `eq-cols` row.

## How to Run

1) Build as usual (offline JSON or API). You should have `index.html` and `style.css` under `figma_images/<Project>`.
2) Run the optimization pipeline:

```bash
python3 tools/apply_project_optimizations.py --root 'figma_images/<Project>'
```

Optional:

```bash
# Drop n-* only when fully covered (opt-in)
export DROP_N_IF_COVERED=true
python3 tools/apply_project_optimizations.py --root 'figma_images/<Project>'

# Enable visual promotion (opt-in)
export PROMOTE_VISUALS=true

# Enable consolidation for non-eq rows (opt-in)
export CONSOLIDATE_NON_EQ=true
python3 tools/postprocess_dedupe.py --root 'figma_images/<Project>' --inject-css --backup --promote-visuals --consolidate-non-eq

# Generate residuals + visuals candidates report
python3 tools/report_residuals.py --root 'figma_images/<Project>' --visuals
```

If anything looks off, restore from backups in the project folder (files like `index.html.bak`, `style.css.bak`).

## What We Reverted (incident and resolution)

- Visual promotion for `.row-item` in `style-common.css` (background/shadow) was rolled back by default after detecting unintended visual spread (e.g., yellowish background/extra shadow). We keep layout/spacing promotion on; visuals remain local unless explicitly identical and safe.

## Next Steps

1) Consolidation scope beyond equalized siblings
   - Apply the same “intersection → base → modifiers” logic to non‑eq rows where layout intent is clear.
   - Gradually reduce `n-*` reliance section‑wide, not only row‑by‑row.

2) Visual promotion – safer, opt‑in
   - Promote background/shadow/radius to base only if all members match exactly in a section cluster.
   - Keep a switch (env or CLI) to enable it on demand and write a visual diff report before applying.

3) Derived modifiers for structure
   - Introduce `__span-2` (and possibly `__span-3`) for equalized rows to express 2x/3x width at the child level:
     - `:where(.eq-cols) > *.__span-2 { flex: 2 1 0 }`

4) Generator‑time row detection (JSON‑based)
   - Add a robust `DetectRowOfBlocks()` that uses Figma Auto Layout (HORIZONTAL), itemSpacing, child geometries (x/y overlap, width/height variance) to tag rows as eq‑cols at build time.
   - Post‑process becomes a safety net instead of first responder.

5) Coverage & diagnostics
   - Emit a “residuals” report listing which `n-*` keep preventing drops and why (e.g., `min-height: 731px`, `transform` etc.).
   - Add a `--visuals` flag to print which visuals are safe to promote.

6) Naming and BEM policy
   - Standardize on `section__row-item` as the section‑scoped base, and `__center`/`__end`/`__between`/`__span-2` as derived modifiers.
   - Keep external spacing (margin) out of base; prefer parent context.

## Guardrails / Principles

- Keep layout and inner spacing in the base; move visuals carefully (opt‑in).
- Differences belong to small, explicit modifiers (leading `__`).
- Quantize to 4px grid to collapse noise.
- Prefer row/section consolidation over element‑by‑element tweaks.
- Backups on every write; one‑step reverts are always possible.

## FAQ

- Q: Why do I still see `n-*` after running the pipeline?
  - A: Either (1) coverage is intentionally conservative; the element isn’t fully covered by base+mods yet, or (2) `DROP_N_IF_COVERED=false`. Turn it on, or promote more props safely.

- Q: Can we keep `n-*` in HTML as fallback, but still manage everything via base classes?
  - A: Yes. That’s the default. `n-*` are retained; base classes instruct the browser. You can drop `n-*` later when confident.

- Q: Will this work on another Figma project?
  - A: Yes. Run `apply_project_optimizations.py` on that project root. The logic is project‑agnostic (uses layout/geometry heuristics, utility intersections and quantization).
