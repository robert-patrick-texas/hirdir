"""Print the newest production release of CPython that uv can install.

"Production" leaves out alphas, betas and release candidates, and the free-threaded
builds. `make upgrade` pins the project to the version this prints.
"""

import json
import re
import subprocess
import sys

PRODUCTION = re.compile(r"\d+\.\d+\.\d+")
LIST_COMMAND = ["uv", "python", "list", "--only-downloads", "--output-format", "json", "cpython"]


def newest(listing: list[dict]) -> str | None:
    """Return the highest production CPython version in uv's listing."""
    versions = [
        entry["version"]
        for entry in listing
        if entry.get("implementation") == "cpython"
        and entry.get("variant") == "default"
        and PRODUCTION.fullmatch(entry.get("version", ""))
    ]
    if not versions:
        return None
    return max(versions, key=lambda version: tuple(int(part) for part in version.split(".")))


def main() -> int:
    """Ask uv what it can download and print the newest production version."""
    result = subprocess.run(  # noqa: S603 - a fixed command
        LIST_COMMAND, capture_output=True, text=True, check=True
    )
    version = newest(json.loads(result.stdout))
    if version is None:
        print("uv lists no production release of CPython", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    sys.exit(main())
