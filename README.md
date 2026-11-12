# hirdir

An inventory of the equipment, virtual machines, software and services a network
operations team answers for, from the purchase request to disposal: what there is,
where it is, who owns it, what it costs to keep supported, how much work it is, and when
it must be replaced.

**Status:** design. No release yet. The pages below are the specification the first
release is being built from.

![Lifecycle workflow](images/lifecycle-workflow.png)

## What it does

- Tracks every item through nine lifecycle states, with what it is for (production,
  spare, staging, excess) and whether it is meant to be online.
- Sets a fact once and lets it fan out. End-of-life dates, estimated value, support
  weight and support cost live on the model and are inherited by every item of that
  model. Contacts and shipping details live on a region or site and are inherited by
  every location beneath. Any of them can be overridden where one item or place differs.
- Understands that four switches in a stack are four things to buy support for, one
  thing on the network, and somewhere between the two to look after.
- Sets the support weight of the infrastructure against the resource units that staff
  positions, outside services, tools and AI provide, for capacity planning.
- Gives technical staff a sortable, filterable grid in the browser, with import and
  export in CSV and JSON.
- Offers the same operations through a versioned API and a command-line client, so
  other tools can feed it and read from it.

## Documentation

| Page | Content |
|---|---|
| [Requirements](docs/requirements.md) | What the product must do, and what it leaves alone |
| [Data model](docs/data-model.md) | The records, inheritance, identity, lifecycle, counting and weight |
| [Architecture](docs/architecture.md) | The software, access, the package and how it is tested |
| [Interfaces](docs/interfaces.md) | The API, the filter grammar, import and export, the CLI, the web UI |
| [Build plan](docs/build-plan.md) | Releases, parallel lanes and the acceptance scenarios |
| [Release process](docs/release-process.md) | Versions, release notes, the dependency rule, publishing these pages |
| [Decisions](docs/decisions.md) | What is decided, what is proposed, what is open |

## At a glance

| | |
|---|---|
| Runs on | Ubuntu 26.04 LTS, installed from one `.deb` under `/opt/hirdir` |
| Server | Python, FastAPI, SQLite |
| Web UI | TypeScript, AG Grid Community |
| In front | nginx from Ubuntu, terminating TLS, at any URL prefix |
| Access | Username and access code for now; three roles; no cookies |

Every example in this repository is fictional.
