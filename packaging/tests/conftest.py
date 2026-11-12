"""Make packaging/hirdir_setup.py importable by the tests beside this file."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
