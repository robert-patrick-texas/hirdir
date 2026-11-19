"""What each route of the API is to the server's own measures and to a server that
refuses (P-265).

A route is one of four. What is **long** by nature, a report, an export, a preview of an
import or of a bulk edit, the check of the kept answers, takes seconds on a server in
good health: its time is in no measure, and a server whose health is very slow turns
it away first, since it can wait. Every other **read** of the API, the pages of lists
among them, is in the measure of time, and is turned away only by a server whose
health is busy. A sign-in and every change that is stored are **kept**: never turned
away, and in the measure, since a save that takes four seconds is a slow server. And
the health routes, About, the server's own measures, the settings and the contract
stand **apart**: never turned away, and in no measure, being asked for by the clock and
answered from memory.

Which of the four a request is, is decided by its route and not by its method alone,
since a list and an export are asked for with `POST` too. Each route is one of them by
what it declares: its path, its method and whether it takes the audit context, which
every route that stores a change does. The few that are not what they so appear are
named here, and a test holds that no route is left to appear as what nobody decided.
"""

import re
from collections.abc import Iterable

from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import compile_path

from hirdir.api import deps
from hirdir.domain.load import APART, KEPT, LONG, READ, Kind

READS = frozenset({"GET"})
# Signing in and the rest of `/auth` are never turned away, whatever their method.
ALWAYS = "/auth/"
# Never turned away and in no measure: the health routes, About and the server's own
# measures, the contract, and the list of the settings, which hold the ceiling itself:
# an Admin who set it too low reads them to set it again.
APART_UNDER = "/health/"
APART_ROUTES = frozenset({"/about", "/about/load", "/openapi.json", "/settings"})
# Every report is worked out when it is asked for.
REPORTS = "/reports/"
# What is asked for with `POST`, stores nothing of the inventory and is long by nature.
# An export and a report with other values tried take no audit context; a preview and
# the check of the kept answers take one, and can wait all the same: nothing of the
# inventory changes until a preview is applied, and applying is never turned away.
LONG_POSTS = frozenset(
    {
        "/exports",
        "/reports/capacity/try",
        "/imports/preview",
        "/items/bulk-update",
        "/kept-answers/check",
    }
)
# A page of a list whose filter is too long for an address: a read like the same asked
# for with `GET`.
READ_POSTS = frozenset(
    {
        "/addresses/query",
        "/catalog-entries/query",
        "/circuit-groups/query",
        "/circuits/query",
        "/device-groups/query",
        "/items/query",
        "/locations/query",
    }
)
# A read that takes the audit context, since it is noted in the audit trail: a read all
# the same.
AUDITED_READS = frozenset({"/reference-files/{hid}/content"})
# How many requests are remembered with what they are, before all are forgotten.
MOST_REMEMBERED = 4096


def _calls(dependant: Dependant) -> Iterable[object]:
    for one in dependant.dependencies:
        yield one.call
        yield from _calls(one)


def audited(route: APIRoute) -> bool:
    """Say whether a route takes the audit context, as one that stores a change does."""
    return deps.get_audit_context in _calls(route.dependant)


def methods_of(route: APIRoute) -> frozenset[str]:
    """Return the methods a route answers."""
    return frozenset(route.methods or ())


def _apart(route: APIRoute) -> bool:
    return route.path.startswith(APART_UNDER) or (
        route.path in APART_ROUTES and methods_of(route) <= READS
    )


def kind_of(route: APIRoute) -> Kind:
    """Return what a route is: `long`, a `read`, `kept` or `apart`."""
    path = route.path
    if _apart(route):
        return APART
    if path.startswith(ALWAYS):
        return KEPT
    if not methods_of(route) <= READS:
        if path in LONG_POSTS:
            return LONG
        return READ if path in READ_POSTS else KEPT
    return LONG if path.startswith(REPORTS) else READ


def undecided(route: APIRoute) -> str | None:
    """Return why nobody has decided what a route is, or None where it is decided. A
    route is decided by what it declares, where that says enough: a `GET` that takes no
    audit context reads, and anything else that takes one stores a change. A `POST`
    that takes none, or a `GET` that takes one, is decided by being named here."""
    path = route.path
    if _apart(route) or path.startswith(ALWAYS):
        return None
    methods = methods_of(route)
    if methods <= READS:
        if audited(route) and path not in AUDITED_READS:
            return "a GET that takes the audit context: name it in AUDITED_READS if it reads"
        return None
    if not methods.isdisjoint(READS):
        return "one route for GET and for another method: give each a route of its own"
    if not audited(route) and path not in LONG_POSTS and path not in READ_POSTS:
        return (
            "it takes no audit context, so it stores no change: name it in READ_POSTS "
            "if it reads, in LONG_POSTS if it is long by nature, or give it the audit "
            "context if it stores a change"
        )
    return None


def routes_of(routers: Iterable[APIRouter]) -> list[APIRoute]:
    """Return the routes of some routers, in the order a request is matched to them."""
    return [route for router in routers for route in router.routes if isinstance(route, APIRoute)]


class Kinds:
    """What a request is, found by its method and its path as the router finds its
    route: the first route, in the order they were declared, whose path and method are
    the request's. What was found is remembered, since every request of the API asks."""

    def __init__(self, routers: Iterable[APIRouter], prefix: str) -> None:
        self._routes: list[tuple[re.Pattern[str], frozenset[str], Kind, str]] = [
            (
                compile_path(prefix + route.path)[0],
                methods_of(route),
                kind_of(route),
                prefix + route.path,
            )
            for route in routes_of(routers)
        ]
        self._found: dict[tuple[str, str], tuple[Kind, str | None]] = {}

    def of(self, method: str, path: str) -> Kind:
        """Return what a request is. One that no route answers is left to the router,
        which says so at once: it stands apart."""
        return self.found(method, path)[0]

    def found(self, method: str, path: str) -> tuple[Kind, str | None]:
        """Return what a request is, and its route as the pattern it was declared
        with, `/api/v1/items/{hid}`: what is kept of a slow request in place of its
        path. None for a request that no route answers."""
        asked = (method, path)
        found = self._found.get(asked)
        if found is None:
            found = self._look(method, path)
            if len(self._found) >= MOST_REMEMBERED:
                self._found.clear()
            self._found[asked] = found
        return found

    def _look(self, method: str, path: str) -> tuple[Kind, str | None]:
        for pattern, methods, kind, route in self._routes:
            if method in methods and pattern.match(path):
                return kind, route
        return APART, None
