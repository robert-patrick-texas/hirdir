# hirdir

![hirdir, source of truth for the fleet](images/hirdir-source-of-truth-for-the-fleet.png)

An inventory for a network operations team: the equipment, virtual machines, software,
services and circuits it answers for, from the purchase request to disposal. What there
is, where it is, who owns it, what it costs to keep supported, how much work it is, and
when it must be replaced.

**Latest release: [0.9.19](docs/releases/v0.9.19.md)** · [All releases](https://github.com/robert-patrick-texas/hirdir/releases) · [Install](docs/install.md) · [Documentation](#documentation)

## Recent updates

- **0.9.19, speed.** A 10,000-row import previews in 27 s and applies in 36 s, where each
  took about three minutes. A large preview runs in the background and the page shows
  how far it has got. Every filtered, sorted page of the item list answers within
  300 ms at 50,000 items.
- **0.9.18, circuits and addresses.** Each side of a circuit has its own dates, and the
  far side can name the carrier network it reaches. Countries and states are picked from
  ISO 3166 lists. Phone numbers, email addresses and names are tidied into one form as
  they are typed or pasted.
- **0.9.17, agents.** Agent accounts act for a person, are held to that person's role
  and are marked in the audit trail. A user's page says where each of its roles comes
  from. Export everything loads back whole into an empty inventory.
- **0.9.16.** `hirdir admin create-user --group` puts a new user in groups.
- **0.9.15.** An account with no role cannot sign in, a Generate button makes a new
  access code, every page from the menu bar opens at its top, and an address can
  belong to an interface.
- **0.9.14, people.** A profile page for whoever signs in; retired user accounts; and a
  person's account, contact and operator retired together.
- **0.9.13, daily work.** A new user made with its contact and operator in one step,
  notes on a user, a colour picker, and every table exported from the Import page.

<details>
<summary>Earlier releases</summary>

- **0.9.10 to 0.9.12.** A health mark in the menu bar and a ceiling past which the server
  asks people to wait; imports and the long reports worked by a second process.
- **0.9.5 to 0.9.9.** Three reviews of the web UI for daily work: search on every page,
  plain-word filters, stacks managed from their rows, and virtual machines, contexts and
  containers linked to their host.
- **0.9.0 to 0.9.4.** Reference files (photos, floor plans, guides) on places and models;
  people as contacts; why each inherited value is what it is; leaderboards on reports.
- **0.8.0, circuits.** Telecom circuits with their two ends, carriers, contacts, monthly
  cost by line and a cost report by fiscal year.
- **0.7.0, renewals.** A renewal worklist and alert, agreements renewed with their
  member contracts, and imports applied in the background.
- **0.6.0 and 0.6.1, money and time.** Support agreements and contracts, coverage and
  end-of-life reports, purchases, and capacity planning.
- **0.5.0, places and people.** Regions, sites and locations, contacts and shipping
  details that pass down, operators and owners.
- **0.4.0 to 0.4.2, structure.** Minor items, stacks, clusters, controller domains and
  addresses.
- **0.1.0 to 0.3.0.** The package, sign-in and accounts; items, models and the
  lifecycle; files and the command line.

Each release's notes are in [docs/releases](docs/releases/v0.9.19.md) and on the
[releases page](https://github.com/robert-patrick-texas/hirdir/releases).

</details>

## What hirdir is

hirdir is the source of truth for what a network team runs. It keeps one record of each
device, model, place, contract, circuit and person, and works out the rest from them:
what is covered by support and until when, what is past its end of life, what each site
costs, and how much work the whole fleet is for the staff who look after it.

It installs from one `.deb` package on Ubuntu, runs behind nginx, and keeps everything
in SQLite. People use it through a web page with a sortable, filterable grid; other
tools use the same operations through a versioned API and a command-line client.

![Lifecycle workflow](images/lifecycle-workflow.png)

## What it does

- **Tracks every item through nine lifecycle states**, with what it is for (production,
  spare, staging, excess) and whether it is meant to be online.
- **Sets a fact once and lets it pass down.** End-of-life dates, value, support weight
  and support cost live on the model and are inherited by every item of it. Contacts and
  shipping details live on a region or site and are inherited by every location beneath.
  Any of them can be overridden where one item or place differs.
- **Understands groups of devices.** Four switches in a stack are four things to buy
  support for, one thing on the network, and somewhere between the two to look after.
- **Follows money and time.** Support agreements and contracts, renewals, coverage and
  end-of-life reports, purchase requests, and circuits with their monthly cost.
- **Plans capacity.** It sets the support weight of the inventory against what staff,
  outside services, tools and AI can carry.
- **Keeps reference files** with the places and models they belong to, served by hirdir
  itself for networks with no internet access.
- **Imports and exports** CSV and JSON, with a preview of every change before it is
  applied, and an audit trail of every change.

## At a glance

| | |
|---|---|
| Runs on | Ubuntu 26.04 LTS, installed from one `.deb` under `/opt/hirdir` |
| Server | Python, FastAPI, SQLite |
| Web UI | TypeScript, React, AG Grid Community |
| In front | nginx from Ubuntu, terminating TLS, at any URL prefix |
| Access | Username and access code; three roles; no cookies |
| Scale | Timed at 50,000 items; a 10,000-row import within a minute |

## Getting started

1. Download the `.deb` from the [latest release](https://github.com/robert-patrick-texas/hirdir/releases/latest).
2. Follow [Install and operate](docs/install.md) to install it, put it behind nginx and
   make the first Admin.
3. To look around, load the fictional [examples](examples/README.md) into an empty
   installation with `hirdir admin load-examples`.

A host with an earlier release is upgraded by installing the new package.

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

## Status

0.9.19 is the latest release. Next is 1.0.0: an accessibility pass, complete user and
operator documentation, backup and restore checked, and the timing run again on the
release. The order of work is in the [build plan](docs/build-plan.md).

Every example in this repository is fictional.

## Licence

[Apache License 2.0](LICENSE.md).
