# hirdir

An inventory of the equipment, virtual machines, software and services a network
operations team answers for, from the purchase request to disposal: what there is,
where it is, who owns it, what it costs to keep supported, how much work it is, and when
it must be replaced.

**Status:** release 0.6.0, money, time and capacity. A support agreement with a
vendor groups contracts, and a contract covers one item or many: what an agreement or
a contract says is said once, and everything beneath has it or overrides it. A
contract is renewed in one place, with its new number and its new period, and every
item under it follows with nothing written to any of them. The coverage report lists
what is in service under no contract, what is covered though out of service and what
runs out soon; the end-of-life report what is past and near each date, by fiscal year;
and a vendor has its portfolio. A purchase request has lines that are received into
items. Items and device groups are registered with external systems. Capacity lines
are balanced against the support weight of the inventory, with and without the
drafts. This stands on 0.5.0, places and people: regions, sites and locations, an
item's location with its site and region, contacts and shipping details that a place
has from the nearest place above it, operators, and owners with their people; on 0.4.0
to 0.4.2, structure: minor items, stacks, clusters and controller domains, addresses,
the condition of an item with what was last observed of it, and the health that
follows; on 0.3.0, files and the command line; on 0.2.0, the inventory itself, with
vendors, a catalog of models, owners and items that inherit from their model and move
through the lifecycle; and on the skeleton of 0.1.0: the package installs and runs
behind nginx, people sign in, and an Admin manages accounts. A set of fictional
[examples](examples/README.md) loads into an empty installation. A host with an
earlier release is upgraded by installing the new package. What is left before 1.0.0
is timing at scale, backup and restore, the upgrade from every release, and an
accessibility pass. The order of work is in the
[build plan](docs/build-plan.md).

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
| [Install and operate](docs/install.md) | Installing the package, nginx, accounts, backup, upgrade |
| [Requirements](docs/requirements.md) | What the product must do, and what it leaves alone |
| [Data model](docs/data-model.md) | The records, inheritance, identity, lifecycle, counting and weight |
| [Architecture](docs/architecture.md) | The software, access, the package and how it is tested |
| [Interfaces](docs/interfaces.md) | The API, the filter grammar, import and export, the CLI, the web UI |
| [Examples](examples/README.md) | A small fictional inventory as CSV and JSON, and how to load it |
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

## Licence

[Apache License 2.0](LICENSE.md).
