"""The server of the acceptance scenarios: `hirdir admin`, started with no ceiling.

The scenarios drive their servers as hard as the host lets them, which says nothing of
the load of a server at work, and a scenario whose list was answered `503` Busy on a
slow host would fail for no fault of what it tries (P-265). So their servers start as
the applications of the tests of the routes do (`no_ceiling` in `tests/conftest.py`):
with no ceiling, until a scenario saves a setting of it, which holds as it does
anywhere. `hirdir admin serve --dev` itself starts with the ceiling its settings have.

Run as `python -m tests.acceptance.serve admin serve --dev`.
"""

from hirdir.cli.main import app
from hirdir.domain import load
from hirdir.io import measures

if __name__ == "__main__":
    measures.at_start = lambda state: load.NO_CEILING
    app()
