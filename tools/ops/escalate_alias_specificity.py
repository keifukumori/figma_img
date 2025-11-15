#!/usr/bin/env python3
import os, runpy
BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
TARGET = os.path.join(BASE, 'escalate_alias_specificity.py')
if __name__ == '__main__':
    runpy.run_path(TARGET, run_name='__main__')
