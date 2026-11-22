"""Write the countries and states that a new inventory starts with (P-318).

The lists are drawn from the ISO 3166 data that Debian and Ubuntu ship in the package
`iso-codes`, read from `/usr/share/iso-codes/json/`: every country of the Americas as
the United Nations' M49 standard groups them, the Caribbean, Central America, South
America and Northern America, each with its ISO 3166-2 subdivisions. Puerto Rico and the
US Virgin Islands are states of the United States here and no countries of their own,
as Guam, American Samoa and the Northern Mariana Islands are, so that an address there
is written one way; the United States Minor Outlying Islands are left out. Where ISO
lists two levels of subdivision, as for the Dominican Republic, the lower one is taken,
the one an address is written with. A country's common name is taken where ISO gives
one ("Bolivia" for "Bolivia, Plurinational State of").

Run once by hand, `uv run python scripts/iso3166_americas.py`, and the file it writes,
beside migration `0019`, which loads it, is committed: the package never reads
`iso-codes`. That file is the migration's and is not changed afterwards: a release that
adds to the lists brings a migration of its own.
"""

import json
import sys
from pathlib import Path

ISO = Path("/usr/share/iso-codes/json")
# The release of `iso-codes` the lists were drawn from, as `dpkg-query -W iso-codes` says.
VERSION = "4.20.1"
OUT = (
    Path(__file__).resolve().parents[1]
    / "src/hirdir/db/migrations/versions/0019_iso3166_americas.json"
)

# UN M49 019, the Americas: 029 Caribbean, 013 Central America, 005 South America and
# 021 Northern America.
# fmt: off
AMERICAS = [
    "AI", "AG", "AW", "BS", "BB", "BQ", "VG", "KY", "CU", "CW", "DM", "DO", "GD", "GP",
    "HT", "JM", "MQ", "MS", "PR", "BL", "KN", "LC", "MF", "VC", "SX", "TT", "TC", "VI",
    "BZ", "CR", "SV", "GT", "HN", "MX", "NI", "PA",
    "AR", "BO", "BV", "BR", "CL", "CO", "EC", "FK", "GF", "GY", "PY", "PE", "GS", "SR",
    "UY", "VE",
    "BM", "CA", "GL", "PM", "US",
]
# fmt: on
# Held as states of the United States, and no countries of their own.
US_STATES_TOO = ("PR", "VI", "GU", "AS", "MP")


def main() -> int:
    countries = json.loads((ISO / "iso_3166-1.json").read_text())["3166-1"]
    subdivisions = json.loads((ISO / "iso_3166-2.json").read_text())["3166-2"]
    by_code = {c["alpha_2"]: c for c in countries}

    rows = []
    for code in AMERICAS:
        if code in US_STATES_TOO:
            continue
        country = by_code[code]
        rows.append([code, country.get("common_name") or country["name"]])

    states = []
    for code, _name in rows:
        mine = [s for s in subdivisions if s["code"].split("-", 1)[0] == code]
        parents = {s.get("parent") for s in mine}
        for s in mine:
            sub = s["code"].split("-", 1)[1]
            if s["code"] in parents:
                continue
            if code == "US" and sub == "UM":
                continue
            states.append([code, sub, s["name"]])
    # The United States first, the rest by name, as the lists are shown.
    rows.sort(key=lambda r: (r[0] != "US", r[1].casefold()))
    states.sort(key=lambda r: (r[0], r[2].casefold()))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(
            {"source": f"iso-codes {VERSION}", "countries": rows, "states": states},
            ensure_ascii=False,
            indent=1,
        )
        + "\n"
    )
    print(f"{len(rows)} countries, {len(states)} states, from iso-codes {VERSION}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
