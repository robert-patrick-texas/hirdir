"""The three roles and their order."""

from collections.abc import Iterable
from enum import StrEnum


class Role(StrEnum):
    """A role. A higher role includes everything a lower one may do."""

    VIEWER = "viewer"
    INVENTORY = "inventory"
    ADMIN = "admin"

    @property
    def rank(self) -> int:
        """The role's place in the order, lowest first."""
        return _RANK[self]

    def allows(self, needed: Role) -> bool:
        """Say whether a holder of this role may do what needs `needed`."""
        return self.rank >= needed.rank


_RANK = {Role.VIEWER: 1, Role.INVENTORY: 2, Role.ADMIN: 3}


def highest(roles: Iterable[str]) -> Role | None:
    """Return the highest of roles, or None when there are none."""
    found = [Role(role) for role in roles]
    return max(found, key=lambda role: role.rank) if found else None
