"""The helper that moves the web UI's npm dependencies for `make upgrade`."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "latest_npm.py"


def _load():
    spec = importlib.util.spec_from_file_location("latest_npm", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MANIFEST = {
    "dependencies": {"react": "19.3.1", "react-dom": "19.3.1"},
    "devDependencies": {"vite": "8.3.8", "vitest": "5.1.0"},
}


def test_behind_moves_only_production_releases_that_differ() -> None:
    latest = {"react": "19.4.0", "react-dom": "19.3.1", "vite": "9.0.0-beta.2", "vitest": "5.2.0"}
    module = _load()
    assert module.behind(MANIFEST, latest) == {
        "--save-prod": ["react@19.4.0"],
        "--save-dev": ["vitest@5.2.0"],
    }
    assert module.prereleases(MANIFEST, latest) == ["vite@9.0.0-beta.2"]


def test_nothing_to_move_when_every_package_is_latest() -> None:
    latest = {"react": "19.3.1", "react-dom": "19.3.1", "vite": "8.3.8", "vitest": "5.1.0"}
    module = _load()
    assert module.behind(MANIFEST, latest) == {}
    assert module.prereleases(MANIFEST, latest) == []
