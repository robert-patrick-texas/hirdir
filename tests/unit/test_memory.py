"""What a long-lived process does with Python's collector once it is made (P-326)."""

import gc

from hirdir.memory import settle


def test_settle_keeps_what_was_made_out_of_the_collectors_passes() -> None:
    before = gc.get_freeze_count()
    try:
        settle()
        assert gc.get_freeze_count() > before
    finally:
        # The test process makes many applications, and keeps none of them for good.
        gc.unfreeze()
