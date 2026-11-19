"""What each route of the API is to a server that is busy (P-265).

A server past its ceiling turns away first what costs most and can wait, the reports,
the exports, the previews of imports and the pages of lists, then every read; a
sign-in, a change that is stored, the health routes, About and the server's own
measures it never turns away. Which of the three a request is, is decided by its route
and not by its method alone, since a list and an export are asked for with `POST` too.

Each route is one of the three by what it declares: its path, its method, what it
answers and whether it takes the audit context, which every route that stores a change
does. The few that are not what they so appear are named here, and a test holds that no
route is left to appear as what nobody decided.
"""

import re
from collections.abc import Iterable

from fastapi import APIRouter
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import compile_path

from hirdir.api import deps, schemas
from hirdir.domain.load import COSTLY, KEPT, READ, Kind

READS = frozenset({"GET"})
# Never turned away, whatever they would otherwise be: signing in and the rest of
# `/auth`, the health routes, About and the server's own measures, the contract, and the
# settings, which hold the ceiling itself: an Admin who set it too low reads them to
# set it again.
ALWAYS = ("/auth/", "/health/")
ALWAYS_ROUTES = frozenset({"/about", "/about/load", "/openapi.json", "/settings"})
# Every report is worked out when it is asked for.
REPORTS = "/reports/"
# What is asked for with `POST` and stores nothing of the inventory: it costs most and
# can wait, as the same asked for with `GET` does. The first three take no audit
# context; a preview and a check of the kept answers take one, and still can wait.
COSTLY_POSTS = frozenset(
    {
        # A page of a list whose filter is too long for an address.
        "/addresses/query",
        "/catalog-entries/query",
        "/circuit-groups/query",
        "/circuits/query",
        "/device-groups/query",
        "/items/query",
        "/locations/query",
        # An export, and a report with other values tried.
        "/exports",
        "/reports/capacity/try",
        # The preview of an import and of a bulk edit: nothing of the inventory changes
        # until it is applied, and applying is never turned away.
        "/imports/preview",
        "/items/bulk-update",
        # Every kept report worked out anew.
        "/kept-answers/check",
    }
)
# A read that takes the audit context, since it is noted in the audit trail: a read all
# the same.
AUDITED_READS = frozenset({"/reference-files/{hid}/content"})


def _calls(dependant: Dependant) -> Iterable[object]:
    for one in dependant.dependencies:
        yield one.call
        yield from _calls(one)


def audited(route: APIRoute) -> bool:
    """Say whether a route takes the audit context, as one that stores a change does."""
    return deps.get_audit_context in _calls(route.dependant)


def pages(route: APIRoute) -> bool:
    """Say whether a route answers a page of a list."""
    answer = route.response_model
    return isinstance(answer, type) and issubclass(answer, schemas.Page)


def methods_of(route: APIRoute) -> frozenset[str]:
    """Return the methods a route answers."""
    return frozenset(route.methods or ())


def kind_of(route: APIRoute) -> Kind:
    """Return what a route is to a server that is busy: `costly`, a `read`, or `kept`."""
    path = route.path
    if path in ALWAYS_ROUTES or path.startswith(ALWAYS):
        return KEPT
    if not methods_of(route) <= READS:
        return COSTLY if path in COSTLY_POSTS else KEPT
    if pages(route) or path.startswith(REPORTS):
        return COSTLY
    return READ


def undecided(route: APIRoute) -> str | None:
    """Return why nobody has decided what a route is, or None where it is decided. A
    route is decided by what it declares, where that says enough: a `GET` that takes no
    audit context reads, and anything else that takes one stores a change. A `POST`
    that takes none, or a `GET` that takes one, is decided by being named here."""
    path = route.path
    if path in ALWAYS_ROUTES or path.startswith(ALWAYS):
        return None
    methods = methods_of(route)
    if methods <= READS:
        if audited(route) and path not in AUDITED_READS:
            return "a GET that takes the audit context: name it in AUDITED_READS if it reads"
        return None
    if not methods.isdisjoint(READS):
        return "one route for GET and for another method: give each a route of its own"
    if not audited(route) and path not in COSTLY_POSTS:
        return (
            "it takes no audit context, so it stores no change: name it in COSTLY_POSTS "
            "if it can wait, or give it the audit context if it stores one"
        )
    return None


def routes_of(routers: Iterable[APIRouter]) -> list[APIRoute]:
    """Return the routes of some routers, in the order a request is matched to them."""
    return [route for router in routers for route in router.routes if isinstance(route, APIRoute)]


class Kinds:
    """What a request is to a server that is busy, found by its method and its path as
    the router finds its route: the first route, in the order they were declared, whose
    path and method are the request's."""

    def __init__(self, routers: Iterable[APIRouter], prefix: str) -> None:
        self._routes: list[tuple[re.Pattern[str], frozenset[str], Kind]] = [
            (compile_path(prefix + route.path)[0], methods_of(route), kind_of(route))
            for route in routes_of(routers)
        ]

    def of(self, method: str, path: str) -> Kind:
        """Return what a request is. One that no route answers is left to the router,
        which says so at once."""
        for pattern, methods, kind in self._routes:
            if method in methods and pattern.match(path):
                return kind
        return KEPT
