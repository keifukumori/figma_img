Project tool classification (pipeline vs ops vs diagnostics)

Pipeline (called from figma_02_build_from_json.py or apply_project_optimizations.py)
- tools/pipeline/postprocess_dedupe.py (wrapper → tools/postprocess_dedupe.py)
- tools/pipeline/unify_styles.py (wrapper → tools/unify_styles.py)
- tools/pipeline/annotate_generic_components.py (wrapper → tools/annotate_generic_components.py)

Ops (optional steps to apply after build; safe, section-scoped)
- tools/ops/assign_section_keys.py (add section-01/02… to <section>)
- tools/ops/add_section_row_alias.py (add SECTION__row, extract gap/align/wrap)
- tools/ops/drop_n_if_covered.py (remove n-* when fully covered)
- tools/ops/neutralize_n_layout_in_section.py (comment out layout props in n-* CSS for a section)
- tools/ops/promote_shadow_to_row_item.py (promote child n-* shadow to SECTION__row-item)
- tools/ops/add_section_card_alias.py (append SECTION__card to elements with card)
- tools/ops/ensure_style_link_order.py (ensure style-common.css is linked after style.css)
- tools/ops/escalate_alias_specificity.py (duplicate :where(.alias){…} as .alias{…})
- tools/ops/mirror_n_selectors_to_alias.py (mirror .n-* selectors in CSS to section aliases)
- tools/ops/alias_graft_for_residual_n.py (append alias to HTML and comma-join simple .n-* rules)
- tools/ops/report_n_drop_blockers.py (report why n-* cannot be dropped yet)

Diagnostics (reports / helpers; not required in pipeline)
- tools/audit_eq_cols.py, tools/report_residuals.py, tools/report_unused_css.py
- tools/detect_spans.py, tools/span_from_json.py
- tools/global_consolidate_components.py, tools/discover_components.py
- tools/canonicalize_bem_variants.py, tools/normalize_stack_alignment.py
- tools/generate_macros.py, tools/build_alias_css_from_html.py
- tools/prune_unused_css_simple.py, tools/prune_trivial_n_classes.py, tools/prune_unused_n_classes.py
- tools/strip_class_token.py, tools/annotate_text_roles.py, tools/annotate_card_roles.py
 - tools/report_n_drop_blockers.py (n-* drop blockers summary)

Notes
- Wrappers under tools/pipeline/ and tools/ops/ call the existing scripts in tools/ to avoid breaking references while we migrate.
- figma_02_build_from_json.py and tools/apply_project_optimizations.py have been updated to reference the pipeline wrappers.
