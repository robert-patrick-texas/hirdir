"""The helper that picks the Python version for `make upgrade`."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "latest_python.py"


def _load():
    spec = importlib.util.spec_from_file_location("latest_python", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_newest_skips_prereleases_and_free_threaded_builds() -> None:
    listing = [
        {"implementation": "cpython", "variant": "default", "version": "3.16.0a1"},
        {"implementation": "cpython", "variant": "freethreaded", "version": "3.15.9"},
        {"implementation": "cpython", "variant": "default", "version": "3.15.2"},
        {"implementation": "cpython", "variant": "default", "version": "3.15.10"},
        {"implementation": "pypy", "variant": "default", "version": "3.99.0"},
    ]
    module = _load()
    assert module.newest(listing) == "3.15.10"
    assert module.newest([]) is None
