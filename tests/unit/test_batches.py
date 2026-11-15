"""How an apply in the background cuts the rows of a file into batches (D-185)."""

from hirdir.io import imports
from hirdir.io.imports import BATCH_ROWS, batches


def test_rows_are_cut_fifty_to_a_batch_in_the_order_they_are_worked() -> None:
    order = [*range(120, 0, -1)]
    cut = batches(order, {})
    assert BATCH_ROWS == 50
    assert [len(batch) for batch in cut] == [50, 50, 20]
    assert [number for batch in cut for number in batch] == order


def test_a_batch_goes_on_to_the_last_row_that_is_checked_with_one_of_its_own() -> None:
    order = list(range(1, 131))
    # Group a has the first row and the sixtieth; b begins in the second batch and ends
    # far beyond it; c is all in the last.
    together = {1: "a", 60: "a", 70: "b", 125: "b", 128: "c", 130: "c"}
    cut = batches(order, together)
    assert [(batch[0], batch[-1]) for batch in cut] == [(1, 60), (61, 125), (126, 130)]
    for key in ("a", "b", "c"):
        holding = [
            place
            for place, batch in enumerate(cut)
            if any(together.get(number) == key for number in batch)
        ]
        assert len(holding) == 1, key


def test_groups_that_overlap_make_one_batch_however_many_rows_that_is() -> None:
    order = list(range(1, 201))
    together = {number: "a" if number % 2 else "b" for number in order}
    assert [len(batch) for batch in batches(order, together)] == [200]
    assert batches([], {}) == []


def test_the_pause_between_batches_is_longer_than_sqlite_waits_between_tries() -> None:
    # SQLite's busy handler tries again every tenth of a second at the longest. A pause
    # shorter than that could pass by a change that waits for the writer's place.
    assert imports.PAUSE_BETWEEN_BATCHES > 0.1
