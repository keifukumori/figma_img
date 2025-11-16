#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
from pathlib import Path


def load_env() -> dict:
    # Prefer local minimal dotenv loader if present
    try:
        from dotenv import load_dotenv  # repository-local minimal loader
        load_dotenv()
    except Exception:
        pass
    env = {k: v for k, v in os.environ.items()}
    # Also try reading .env in CWD if not loaded
    if not Path('.env').exists():
        return env
    try:
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith('#'):
                    continue
                if '=' in s:
                    k, v = s.split('=', 1)
                    env.setdefault(k.strip(), v.strip())
    except Exception:
        pass
    return env


def bool_env(env: dict, key: str, default: bool = False) -> bool:
    v = env.get(key)
    if v is None:
        return default
    return str(v).lower() in ('true', '1', 'on', 'yes')


def safe_name(name: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\-_]+", "-", (name or '').strip())
    s = re.sub(r"-+", "-", s).strip('-')
    return s or 'Project'


def detect_project_root(env: dict) -> dict:
    out_dir = env.get('OUTPUT_DIR', 'figma_images')
    input_json = env.get('INPUT_JSON_FILE')
    project = None
    if input_json and Path(input_json).exists():
        try:
            import json as _json
            data = _json.loads(Path(input_json).read_text(encoding='utf-8'))
            project = data.get('name') or 'Project'
        except Exception:
            project = 'Project'
    else:
        # Fallback: first dir under OUTPUT_DIR with index.html
        p = Path(out_dir)
        if p.exists():
            for sub in sorted(p.iterdir()):
                if sub.is_dir() and (sub / 'index.html').exists():
                    project = sub.name
                    break
    if not project:
        project = 'Project'

    # Prefer unsanitized project dir if it exists (handles i18n names)
    raw_root = Path(out_dir) / project
    san_root = Path(out_dir) / safe_name(project)
    if raw_root.exists():
        root = raw_root
    else:
        root = san_root

    # Try to locate canonical index.html under chosen root; if not found, scan OUTPUT_DIR broadly
    canonical = None
    if (root / 'index.html').exists():
        canonical = str(root / 'index.html')
    else:
        for base, dirs, files in os.walk(root if root.exists() else Path(out_dir)):
            if 'index.html' in files and 'style.css' in files:
                canonical = str(Path(base) / 'index.html')
                # prefer a base that looks like our project name if multiple candidates
                # break on first if scanning under root; otherwise keep searching for better match
                if root.exists():
                    break
        # As a last resort, pick the first subdir in OUTPUT_DIR that has both files
        if canonical is None:
            p = Path(out_dir)
            if p.exists():
                for sub in sorted(p.iterdir()):
                    if sub.is_dir() and (sub / 'index.html').exists() and (sub / 'style.css').exists():
                        root = sub
                        canonical = str(sub / 'index.html')
                        break

    # Collect additional htmls
    htmls = []
    if root.exists():
        for hp in root.rglob('*.html'):
            try:
                htmls.append(str(hp))
            except Exception:
                pass
    return {
        'project_name': project,
        'output_root': str(root),
        'canonical_index_html': canonical,
        'all_html': sorted(htmls),
    }


def main():
    env = load_env()
    plan = {
        'core': [
            'figma_02_build_from_json.py',
            'fetch_figma_layout.py',
        ],
        'pipeline': [],
        'ops': [],
        'reports': [],
        'settings': {
            'SINGLE_DOM': bool_env(env, 'SINGLE_DOM', True),
            'TEXT_TOKEN_MODE': env.get('TEXT_TOKEN_MODE', 'off'),
            'N_NODE_VISUAL_ONLY': bool_env(env, 'N_NODE_VISUAL_ONLY', True),
            'SECTION_WRAPPER_MODE': env.get('SECTION_WRAPPER_MODE', 'compact'),
            'FLATTEN_SHALLOW_WRAPPERS': bool_env(env, 'FLATTEN_SHALLOW_WRAPPERS', False),
        },
    }

    # Pipeline toggles
    if bool_env(env, 'POSTPROCESS_COMMON', False):
        plan['pipeline'].append('tools/pipeline/postprocess_dedupe.py')
    if bool_env(env, 'POSTPROCESS_COMPONENTS', False):
        plan['pipeline'].append('tools/pipeline/annotate_generic_components.py')
    if bool_env(env, 'POSTPROCESS_UNIFY', False):
        plan['pipeline'].append('tools/pipeline/unify_styles.py')

    # Ops toggles (subset)
    mapping = [
        ('POST_OPS_ASSIGN_SECTIONS', 'tools/ops/assign_section_keys.py'),
        ('POST_OPS_ADD_SECTION_ROW_ALIAS', 'tools/ops/add_section_row_alias.py'),
        ('POST_OPS_ADD_SECTION_CARD_ALIAS', 'tools/ops/add_section_card_alias.py'),
        ('POST_OPS_ENSURE_STYLE_ORDER', 'tools/ops/ensure_style_link_order.py'),
        ('POST_OPS_PRUNE_REDUNDANT_CLASSES', 'tools/ops/prune_redundant_classes.py'),
        ('POST_OPS_ESCALATE_ALIAS_SPECIFICITY', 'tools/ops/escalate_alias_specificity.py'),
        ('POST_OPS_MIRROR_N_SELECTORS', 'tools/ops/mirror_n_selectors_to_alias.py'),
        ('POST_OPS_ALIAS_GRAFT', 'tools/ops/alias_graft_for_residual_n.py'),
        ('POST_OPS_DROP_N_IF_COVERED', 'tools/ops/drop_n_if_covered.py'),
        ('POST_OPS_PRUNE_UNUSED_N_CSS', 'tools/ops/prune_unused_n_css_rules.py'),
        ('POST_OPS_CANONICALIZE_BEM', 'tools/ops/canonicalize_bem.py'),
        ('POST_OPS_PROPOSE_SECTION_BREAKS', 'tools/ops/propose_section_breaks.py'),
        ('POST_OPS_APPLY_SECTION_BREAKS', 'tools/ops/apply_section_breaks.py'),
    ]
    for key, path in mapping:
        if bool_env(env, key, False):
            plan['ops'].append(path)

    # Reports that may be used
    # n-drop blockers is often invoked manually during migration
    plan['reports'].append('tools/report_n_drop_blockers.py')

    info = detect_project_root(env)
    plan['outputs'] = info

    out_path = Path('tools/runtime_plan.json')
    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(plan, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
