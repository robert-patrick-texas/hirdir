# hirdir

An inventory of the equipment, virtual machines, software and services a network
operations team answers for, from the purchase request to disposal: what there is,
where it is, who owns it, what it costs to keep supported, how much work it is, and when
it must be replaced.

**Status:** release 0.4.0, structure. An item may be in another item: a power supply
or a module has the owner and the lifecycle state of its switch unless it is given its
own, and is not counted. Switches are grouped into stacks, controllers into clusters,
and controllers with their access points or phones into controller domains, with the
dates each member joined and left; a stack shows the serial number of its master, and
an item that is replaced hands its place in the stack to the one that took it. Items
and groups have addresses, under network labels where there are any, and an address
held twice under one network is reported. The summary counts a view of the inventory:
components beside managed nodes, support weight with the stack discount, estimated
value and annual support cost. This stands on 0.3.0, files and the command line, on
0.2.0, the inventory itself, with vendors, a catalog of models, owners and items that
inherit from their model and move through the lifecycle, and on the skeleton of 0.1.0:
the package installs and runs behind nginx, people sign in, and an Admin manages
accounts. A set of fictional [examples](examples/README.md) loads into an empty
installation. A host with an earlier release is upgraded by installing the new
package. Regions, sites, locations and contacts arrive with 0.5.0. The order of work
is in the [build plan](docs/build-plan.md).

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
