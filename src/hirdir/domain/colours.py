"""The colours a form offers: a grid of 64, a slider of 32, and the next for an operator.

A colour is stored as `#rrggbb`, whatever it is (`tags.COLOUR`): the grid and the slider
are what a form offers to press, and a colour that is not among them is as good as one
that is (P-285). The values are fixed here, so that every form, every page and every
client offers the same ones: eight hues in the order of the rainbow, each in eight
shades from the lightest to the darkest, drawn once at even steps of lightness and
written down.
"""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from hirdir.db.models import Operator

# The hues, in the order of the rainbow, each with its eight shades, lightest first.
HUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "red",
        ("#fee0dc", "#febfb7", "#ff968a", "#f66d62", "#e24942", "#be2f2c", "#94221f", "#6c1614"),
    ),
    (
        "orange",
        ("#fee2cf", "#ffc29a", "#fb9d59", "#ec7c0e", "#c96805", "#a35303", "#7e3f02", "#5c2b00"),
    ),
    (
        "yellow",
        ("#f4e8bb", "#e5d183", "#d3b63b", "#bb9c00", "#9e8406", "#7f6a03", "#625101", "#463a00"),
    ),
    (
        "green",
        ("#d0f3d0", "#a8e3a9", "#7acf7e", "#4db956", "#11a22f", "#028321", "#016517", "#00480e"),
    ),
    (
        "teal",
        ("#b9f5f4", "#7ae6e5", "#0cd1d1", "#0db5b5", "#009a9a", "#027c7c", "#045f5f", "#004444"),
    ),
    (
        "blue",
        ("#d9eaff", "#b3d4ff", "#86bafe", "#54a0fe", "#1d84f5", "#0169cd", "#0050a0", "#003975"),
    ),
    (
        "violet",
        ("#ebe3fe", "#d9c6fe", "#c4a4fe", "#b082f7", "#9964e5", "#7e4ac2", "#613897", "#45266e"),
    ),
    (
        "pink",
        ("#ffddec", "#febad9", "#f990c4", "#e96cad", "#d44996", "#b2307a", "#8a235e", "#651643"),
    ),
)
SHADES = 8

# The grid: a row to each shade, the lightest first, and in each row the eight hues in
# the order of the rainbow, so that a hue is a column.
GRID: tuple[tuple[str, ...], ...] = tuple(
    tuple(shades[shade] for _, shades in HUES) for shade in range(SHADES)
)

# The slider: the four middle shades of each hue, hue after hue in the order of the
# rainbow, each from its lighter to its darker.
MIDDLE = (2, 3, 4, 5)
SLIDER: tuple[str, ...] = tuple(shades[shade] for _, shades in HUES for shade in MIDDLE)

# The order in which a new operator is given a colour: the darker of the middle shades
# first, which are read best beside a label, and within a shade the hues far apart, so
# that the first eight operators have eight hues.
_APART = ("blue", "orange", "green", "pink", "teal", "red", "violet", "yellow")
_BY_HUE = dict(HUES)
NEXT_ORDER: tuple[str, ...] = tuple(_BY_HUE[hue][shade] for shade in (5, 4, 3, 2) for hue in _APART)


def next_of(used: Counter[str]) -> str:
    """Return the first colour of `NEXT_ORDER` that is not used, or the least used.

    `used` counts how often each colour is held, in lower case. Where every colour of
    the order is taken, the one held least often is given, the earliest of those.
    """
    return min(NEXT_ORDER, key=lambda colour: used[colour])


def next_for_operators(db: Session) -> str:
    """Return the colour that the next operator is given, where none is chosen.

    A retired operator holds no colour: its label stands for nothing, and its colour is
    free again.
    """
    held = db.scalars(
        select(Operator.colour).where(
            Operator.record_status != "retired", Operator.colour.is_not(None)
        )
    )
    return next_of(Counter(colour.lower() for colour in held if colour))
