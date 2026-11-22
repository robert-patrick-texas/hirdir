# Examples

A small, fictional inventory: one file for each kind of record, as CSV and as JSON. The
two formats hold the same records. Every host name, serial number, asset tag, date and
amount here is invented, and so are the end-of-life dates and the prices of the models.
Only the names of manufacturers and models are real.

The files are written by `make examples`, which builds this inventory in a database of
its own and exports it. They are not edited by hand.

## Loading them

On the server, into an inventory that holds nothing yet, one command loads them all, and
`hirdir admin reset` clears them again, with whatever was added beside them:

```bash
sudo systemctl stop hirdir
sudo hirdir admin load-examples
sudo systemctl start hirdir
```

To see what an import does, load them one at a time instead, in this order, because a
record names the ones it refers to:

1. `countries.csv`
2. `states.csv`
3. `tags.csv`
4. `vendors.csv`
5. `catalog-entries.csv`
6. `contacts.csv`
7. `vendor-contacts.csv`
8. `operators.csv`
9. `regions.csv`
10. `sites.csv`
11. `locations.csv`
12. `contact-assignments.csv`
13. `owners.csv`
14. `owner-members.csv`
15. `networks.csv`
16. `external-systems.csv`
17. `agreements.csv`
18. `contracts.csv`
19. `contract-contacts.csv`
20. `purchase-requests.csv`
21. `purchase-lines.csv`
22. `device-groups.csv`
23. `items.csv`
24. `device-group-members.csv`
25. `item-replacements.csv`
26. `addresses.csv`
27. `contract-coverage.csv`
28. `registrations.csv`
29. `capacity-lines.csv`
30. `circuit-groups.csv`
31. `circuits.csv`
32. `circuit-carriers.csv`
33. `circuit-costs.csv`
34. `circuit-contacts.csv`
35. `circuit-devices.csv`

Each command shows a preview and changes nothing. Add `--apply` to load the file.

```bash
hirdir import examples/countries.csv --entity countries
hirdir import examples/states.csv --entity states
hirdir import examples/tags.csv --entity tags
hirdir import examples/vendors.csv --entity vendors
hirdir import examples/catalog-entries.csv --entity catalog_entries
hirdir import examples/contacts.csv --entity contacts
hirdir import examples/vendor-contacts.csv --entity vendor_contacts
hirdir import examples/operators.csv --entity operators
hirdir import examples/regions.csv --entity regions
hirdir import examples/sites.csv --entity sites
hirdir import examples/locations.csv --entity locations
hirdir import examples/contact-assignments.csv --entity contact_assignments
hirdir import examples/owners.csv --entity owners
hirdir import examples/owner-members.csv --entity owner_members
hirdir import examples/networks.csv --entity networks
hirdir import examples/external-systems.csv --entity external_systems
hirdir import examples/agreements.csv --entity agreements
hirdir import examples/contracts.csv --entity contracts
hirdir import examples/contract-contacts.csv --entity contract_contacts
hirdir import examples/purchase-requests.csv --entity purchase_requests
hirdir import examples/purchase-lines.csv --entity purchase_lines
hirdir import examples/device-groups.csv --entity device_groups
hirdir import examples/items.csv --entity items
hirdir import examples/device-group-members.csv --entity device_group_members
hirdir import examples/item-replacements.csv --entity item_replacements
hirdir import examples/addresses.csv --entity addresses
hirdir import examples/contract-coverage.csv --entity contract_coverage
hirdir import examples/registrations.csv --entity registrations
hirdir import examples/capacity-lines.csv --entity capacity_lines
hirdir import examples/circuit-groups.csv --entity circuit_groups
hirdir import examples/circuits.csv --entity circuits
hirdir import examples/circuit-carriers.csv --entity circuit_carriers
hirdir import examples/circuit-costs.csv --entity circuit_costs
hirdir import examples/circuit-contacts.csv --entity circuit_contacts
hirdir import examples/circuit-devices.csv --entity circuit_devices
```

The first two files are the lists of countries and states that an address takes its
country and its state from, as every new inventory has them: loaded into one, each of
their rows is `unchanged`, and a row that adds or changes a country or a state is an
Admin's to apply. `hirdir admin load-examples` leaves them out, since `hirdir admin
reset` keeps the lists, as it keeps the choices.

Loaded a second time, every row is `unchanged`. The `hid` column is there and blank:
`hirdir` gives each record its HID as it is created. A file exported from a running
`hirdir` has the column filled in, and a row with an HID changes that record and no
other.

The columns of each file, and what an import does with a blank cell or with `!clear`,
are under "Import and export" in [Interfaces](../docs/interfaces.md#import-and-export).
