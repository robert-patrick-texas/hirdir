"""The committed OpenAPI document and the committed examples match the code."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_contract_file_is_current() -> None:
    result = subprocess.run(  # noqa: S603 - a fixed command on our own script
        [sys.executable, str(ROOT / "scripts" / "write_contract.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_examples_are_current() -> None:
    result = subprocess.run(  # noqa: S603 - a fixed command on our own script
        [sys.executable, str(ROOT / "scripts" / "seed_examples.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
