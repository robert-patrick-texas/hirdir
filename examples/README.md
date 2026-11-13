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
4. `owners.csv`
5. `items.csv`

Each command shows a preview and changes nothing. Add `--apply` to load the file.

```bash
hirdir import examples/tags.csv --entity tags
hirdir import examples/vendors.csv --entity vendors
hirdir import examples/catalog-entries.csv --entity catalog_entries
hirdir import examples/owners.csv --entity owners
hirdir import examples/items.csv --entity items
```

Loaded a second time, every row is `unchanged`. The `hid` column is there and blank:
`hirdir` gives each record its HID as it is created. A file exported from a running
`hirdir` has the column filled in, and a row with an HID changes that record and no
other.

The columns of each file, and what an import does with a blank cell or with `!clear`,
are under "Import and export" in [Interfaces](../docs/interfaces.md#import-and-export).
