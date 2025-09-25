#!/usr/bin/env python3
"""
Step 04: Post-process generated HTML/CSS to add reusable flex utilities safely.

This is a thin wrapper around tools/postprocess_dedupe.py so you can run:

  python figma_04_postprocess_dedupe.py --root figma_images/<Project>

Flags pass-through to the underlying tool:
  --dry-run                 Report only (style-buckets.json)
  --inject-css             Write style-common.css + inject <link> + add utility classes
  --comment-out-covered    Conservatively comment out flex props covered by utilities in style.css
  --backup                 Create .bak before modifying HTML/CSS
  --min-occurs N           Minimum occurrences for a pattern (default 3)
  --props ...              Comma-separated prop whitelist (default: display,flex-direction,justify-content,align-items,gap,flex-wrap)
"""

import sys
import os


def main():
    # Ensure repo root is on sys.path so we can import tools.*
    repo_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, repo_root)
    from tools.postprocess_dedupe import main as tool_main  # type: ignore
    tool_main()


if __name__ == "__main__":
    main()

