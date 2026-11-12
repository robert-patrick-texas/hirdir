"""Write the OpenAPI document of the API to contract/openapi.json.

The document is the contract between the server and its clients. The web UI's types are
generated from this file, and a test fails when the file is out of date.
"""

import json
import sys
import tempfile
from pathlib import Path

from hirdir.app import create_app
from hirdir.config import Config

TARGET = Path(__file__).resolve().parent.parent / "contract" / "openapi.json"


def render() -> str:
    """Return the OpenAPI document as stable, readable JSON."""
    with tempfile.TemporaryDirectory() as state:
        document = create_app(Config(state_dir=Path(state))).openapi()
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def main() -> int:
    """Write the document, or with --check say whether the file is current."""
    text = render()
    if "--check" in sys.argv:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != text:
            print("contract/openapi.json is out of date: run `make contract`", file=sys.stderr)
            return 1
        return 0
    TARGET.parent.mkdir(exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(TARGET.parent.parent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
