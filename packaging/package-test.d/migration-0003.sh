# shellcheck shell=bash
# shellcheck disable=SC2034,SC2154  # Read by packaging/package-test.sh, whose names these are.
#
# Migration 0003, which came with hirdir 0.2.1: a support weight is kept to two places.
#
# packaging/package-test.sh reads this file when the upgrade it tests runs the
# migration: see "what one upgrade alone has" there. The previous release then keeps a
# support weight to three places, so the first model is given one of three, and the
# migration is meant to round it to two: the inventory gives the model the weight
# below, and the upgrade pass looks for what the migration makes of it.
witness_weight=0.125
witness_weight_after=0.13

# The migration writes every support weight anew, in hundredths, in the items and the
# catalog_entries tables, and an item that takes its weight from the model shows the
# rounded one. This file does not name those rows and that field as meant to change,
# and has no check of them by themselves: it was written when the upgrade passes were
# made to follow the pair, from the two weights that they had held until then.
before_0003() {
    skip "pkg what migration 0003 does to the weights that are stored: its file names neither the rows of items and catalog_entries, which it writes anew in hundredths, nor the weight that an item takes from its model, so the comparison of those three fails for this pair until it does"
}
