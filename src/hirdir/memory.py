"""What a long-lived process of hirdir does with Python's collector once it is made."""

import gc


def settle() -> None:
    """Collect what is garbage once, then keep every object made so far out of the
    collector's later passes, so that they are not walked again and again.

    A process that serves or works is started with tens of thousands of objects that
    live as long as it does: the modules, the application, its routes and schemas. Each
    full pass of Python's collector walks every one of them, and on the fixture of 50,000
    items such a pass took 140 to 340 ms, about once in ten requests of the item list,
    which made the slowest of fifteen runs twice the median. Kept out once the process is
    made, they no longer are (P-326). Called by `hirdir admin serve`, by `hirdir admin
    work` and by the timing, never by the tests, which make many applications and
    would keep each of them.
    """
    gc.collect()
    gc.freeze()
