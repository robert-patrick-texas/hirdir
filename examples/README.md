# Examples

A small, fictional inventory: one file for each kind of record, as CSV and as JSON. The
two formats hold the same records. Every host name, serial number, asset tag, date and
amount here is invented, and so are the end-of-life dates and the prices of the models.
Only the names of manufacturers and models are real.

The files are written by `make examples`, which builds this inventory in a database of
its own and exports it. They are not edited by hand.

## Loading them

Load the files in this order, because a record names the ones it refers to:

1. `tags.csv`
2. `vendors.csv`
3. `catalog-entries.csv`
4. `contacts.csv`
5. `vendor-contacts.csv`
6. `operators.csv`
7. `regions.csv`
8. `sites.csv`
9. `locations.csv`
10. `contact-assignments.csv`
11. `owners.csv`
12. `owner-members.csv`
13. `networks.csv`
14. `external-systems.csv`
15. `agreements.csv`
16. `contracts.csv`
17. `contract-contacts.csv`
18. `purchase-requests.csv`
19. `purchase-lines.csv`
20. `items.csv`
21. `device-groups.csv`
22. `device-group-members.csv`
23. `item-replacements.csv`
24. `addresses.csv`
25. `contract-coverage.csv`
26. `registrations.csv`
27. `capacity-lines.csv`
28. `circuit-groups.csv`
29. `circuits.csv`
30. `circuit-carriers.csv`
31. `circuit-costs.csv`
32. `circuit-contacts.csv`
33. `circuit-devices.csv`

Each command shows a preview and changes nothing. Add `--apply` to load the file.

```bash
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
hirdir import examples/items.csv --entity items
hirdir import examples/device-groups.csv --entity device_groups
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

Loaded a second time, every row is `unchanged`. The `hid` column is there and blank:
`hirdir` gives each record its HID as it is created. A file exported from a running
`hirdir` has the column filled in, and a row with an HID changes that record and no
other.

The columns of each file, and what an import does with a blank cell or with `!clear`,
are under "Import and export" in [Interfaces](../docs/interfaces.md#import-and-export).
