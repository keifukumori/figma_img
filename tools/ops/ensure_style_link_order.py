#!/usr/bin/env python3
import os, runpy
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TARGET = os.path.join(BASE, 'ensure_style_link_order.py')
if __name__ == '__main__':
    runpy.run_path(TARGET, run_name='__main__')
