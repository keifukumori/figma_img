#!/usr/bin/env python3
import os, runpy, sys
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TARGET = os.path.join(BASE, 'neutralize_n_layout_in_section.py')
if __name__ == '__main__':
    sys.exit(runpy.run_path(TARGET, run_name='__main__'))

