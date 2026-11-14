.PHONY: help version dev web check fmt test test-changed acceptance e2e deb package-test docs docs-watch facts release-body upgrade guard contract examples

# The tests run several at once: as many as the host has cores and memory free. Before
# they start, a busy host is waited for, ten minutes at the most. HIRDIR_TEST_WORKERS
# sets the number outright and HIRDIR_TEST_WAIT the longest wait, in seconds. See
# scripts/test_load.py.
WORKERS = $$(uv run python scripts/test_load.py --wait)
PYTEST = uv run pytest --numprocesses $(WORKERS) --dist worksteal

help:           ## list the targets
	@grep -E '^[a-z-]+: .*##' Makefile | sed -E 's/:.*## /\t/' | expand -t 16

version:        ## print the version
	@sed -n 's/^__version__ = "\(.*\)"/\1/p' src/hirdir/__init__.py

dev:            ## run the server for development on 127.0.0.1:8715 with data in ./dev-data
	HIRDIR_CONFIG=dev-data/config.toml uv run hirdir admin serve --dev

web:            ## build the web UI into src/hirdir/static
	npm --prefix web ci
	npm --prefix web run build

fmt:            ## format the Python
	uv run ruff format .
	uv run ruff check --fix .

check: guard    ## format check, lint, type check and tests, for the server and the web UI
	uv run ruff format --check .
	uv run ruff check .
	uv run ty check
	$(PYTEST) tests/unit tests/api packaging/tests
	@if [ -d web/node_modules ]; then npm --prefix web run check; else echo "web: skipped, run 'make web' first"; fi

test:           ## the Python tests only
	$(PYTEST) tests/unit tests/api packaging/tests

test-changed:   ## only the Python tests that what has changed since their last run can reach; for use while working, never in place of `make check`
	$(PYTEST) --testmon tests/unit tests/api packaging/tests

guard:          ## refuse to go on if a tracked file holds a term listed in .publish-guard
	@uv run python scripts/publish_guard.py

contract:       ## write the OpenAPI document to contract/openapi.json
	uv run python scripts/write_contract.py

examples:       ## write examples/ by exporting the seeded example database
	uv run python scripts/seed_examples.py

acceptance:     ## the scenarios of docs/build-plan.md against a server started from an empty database
	$(PYTEST) tests/acceptance

e2e:            ## package-test, with the browser scenarios run against the fresh install
	packaging/package-test.sh --e2e

deb: web docs   ## build dist/hirdir_<version>_amd64.deb in a clean container, with the web UI and the documentation of this tree
	packaging/build-deb.sh

package-test:   ## install the package in systemd containers and exercise it through nginx: upgraded from the previous release, with a migration that fails, and fresh
	packaging/package-test.sh

docs:           ## render every .md file into html/
	uv run --only-group docs python scripts/build_docs.py

docs-watch:     ## and rebuild whenever a source changes
	uv run --only-group docs python scripts/build_docs.py --watch

facts:          ## print the release notes' Lines of code and Versions, after make deb
	@uv run python scripts/release_facts.py

release-body:   ## print the release notes as the GitHub release takes them: each paragraph on one line
	@uv run python scripts/release_body.py $(VERSION)

upgrade:        ## move every dependency to its latest production release, then check
	-uv self update
	uv python install "$$(uv run python scripts/latest_python.py)"
	uv python pin "$$(uv run python scripts/latest_python.py)"
	uv lock --upgrade
	uv sync --all-groups
	@if [ -f web/package.json ]; then cd web && npx --yes npm-check-updates -u && npm install && npm run build; fi
	$(MAKE) check
