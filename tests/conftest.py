"""
tests/conftest.py — Pytest session configuration.

Adds src/ to sys.path so all test files can do `from domain.xxx import yyy`
without needing a full package install.
"""
import sys
import os

# Ensure src/ is on the import path for all tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
