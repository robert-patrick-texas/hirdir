# Working on hirdir

Instructions for an agent building this project. Read this page, then
[docs/decisions.md](docs/decisions.md), then the pages your task touches.

## Where we are

The next release is the first row of the table in
[docs/build-plan.md](docs/build-plan.md) that has no file in `docs/releases/`.

## Authority

1. The documentation in `docs/` says what to build. Field names, routes and rules are
   taken from it exactly.
2. `docs/decisions.md` records every choice. "Decided" is fixed. "Proposed" is the
   working answer: build it, and keep it easy to change. "Open" is not to be settled in
   code.
3. If the documentation is silent or wrong, add a proposal to `docs/decisions.md`, take
   the safest reading, and say so in your report. Change the documentation and the
   OpenAPI contract before the code.

## Non-negotiables

- **Nothing real is committed.** No name, host name, address, serial number, contract
  number, count or screenshot from a real network, in code, tests, fixtures, examples or
  documentation. Use the reserved documentation address ranges. See "Example data" in
  [docs/requirements.md](docs/requirements.md).
- **No cookies**, ever, on any response.
- **Rules live in `src/hirdir/domain/` and `src/hirdir/io/`.** Routers and CLI commands
  hold none. The CLI's client commands call the API; only `hirdir admin` touches the
  database.
- **Every write is role-checked on the server and audited.**
- **Every record is referenced by HID.** Names are for people and for matching imports.
- **Inherited values are never copied down.** They are resolved when read, and returned
  with their source.
- **Items are retired or archived, never deleted.**
- **Latest production releases only.** Do not pin below the latest without a waiver in
  `docs/waivers.md`.
- **SQL that differs between SQLite and PostgreSQL goes in `src/hirdir/db/dialect.py`.**

## Project mechanics

| Task | Command |
|---|---|
| Set up | `uv sync` and `npm --prefix web ci` |
| Run for development | `make dev` |
| Format, lint, type-check, test | `make check` |
| Python tests that a change can reach, while working | `make test-changed` |
| Acceptance scenarios | `make acceptance` |
| Build the web UI | `make web` |
| Build the package | `make deb` |
| Install and exercise the package in a container | `make package-test` |
| Build the documentation | `make docs` |
| Tables for the release notes | `make facts` |
| Move every dependency to its latest release | `make upgrade` |

The tests run several at once and wait for a busy host, ten minutes at the most: see
"How long the tests take" in [docs/architecture.md](docs/architecture.md#testing).
`make test-changed` is for the minutes between changes; a task is done by `make check`
and `make acceptance`.

Python is run through `uv run`. Formatting and linting are `ruff`; type checking is
`ty`. Do not silence a rule to make a check pass.

Work on a branch. Commit when a task is done and its checks pass. Do not push, tag or
publish a release unless asked.

## Definition of done

The list at the end of [docs/build-plan.md](docs/build-plan.md). In short: documented,
in the contract, tested where it can fail, `make check` clean, audited and
role-checked, nothing real in any file.

## Report

End a task with: what was built, which scenarios now pass, what was not done and why,
any proposal added to `docs/decisions.md`, and anything a person must decide.
