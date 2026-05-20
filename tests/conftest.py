"""
tests/conftest.py — Pytest session configuration.

Adds src/ to sys.path so all test files can do `from domain.xxx import yyy`
without needing a full package install.
"""
import sys
import os

# Shim pkg_resources to prevent ImportError in pytest-html on Python 3.12+ / 3.14+
try:
    import pkg_resources
except ImportError:
    from types import ModuleType
    pkg_resources_shim = ModuleType("pkg_resources")
    class DistributionNotFound(Exception):
        pass
    def get_distribution(dist):
        class Dist:
            version = "1.0.0"
        return Dist()
    pkg_resources_shim.get_distribution = get_distribution  # type: ignore
    pkg_resources_shim.DistributionNotFound = DistributionNotFound  # type: ignore
    sys.modules["pkg_resources"] = pkg_resources_shim

# Ensure src/ is on the import path for all tests
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

