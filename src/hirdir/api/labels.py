"""The routes of labels and lists: tags, choices, settings and the lifecycle rules."""

from fastapi import APIRouter

from hirdir.api import records as r
from hirdir.api import shapes
from hirdir.api.deps import Admin, Audit, Db, Inventory, Viewer
from hirdir.domain import choices, lifecycle, settings, tags

tag_routes = APIRouter(prefix="/tags", tags=["Labels and lists"])
choice_routes = APIRouter(prefix="/choices", tags=["Labels and lists"])
setting_routes = APIRouter(prefix="/settings", tags=["Labels and lists"])
rule_routes = APIRouter(prefix="/lifecycle-rules", tags=["Labels and lists"])


def _changes(body: r.Model) -> dict:
    return body.model_dump(exclude={"row_version"}, exclude_unset=True)


# --- tags ----------------------------------------------------------------------------


@tag_routes.get("")
def list_tags(_: Viewer, db: Db) -> list[r.TagOut]:
    """List every tag by label, with the number of records that carry it."""
    return [shapes.tag_out(tag, uses) for tag, uses in tags.list_tags(db)]


@tag_routes.post("", status_code=201)
def create_tag(body: r.TagCreate, _: Inventory, context: Audit, db: Db) -> r.TagOut:
    """Create a tag."""
    return shapes.tag_out(tags.create_tag(db, context, body.model_dump()), 0)


@tag_routes.patch("/{hid}")
def update_tag(hid: str, body: r.TagPatch, _: Inventory, context: Audit, db: Db) -> r.TagOut:
    """Change a tag. A new label shows on every record that carries the tag."""
    tag = tags.update_tag(db, context, hid, body.row_version, _changes(body))
    uses = {found.hid: count for found, count in tags.list_tags(db)}
    return shapes.tag_out(tag, uses.get(tag.hid, 0))


@tag_routes.delete("/{hid}", status_code=204)
def delete_tag(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a tag that no record carries."""
    tags.delete_tag(db, context, hid)


# --- choices -------------------------------------------------------------------------


@choice_routes.get("")
def list_choices(_: Viewer, db: Db, list: str = "") -> list[r.ChoiceOut]:
    """List the choices of one list, or of every list, in their order."""
    return [shapes.choice_out(choice) for choice in choices.list_choices(db, list)]


@choice_routes.post("", status_code=201)
def create_choice(body: r.ChoiceCreate, _: Inventory, context: Audit, db: Db) -> r.ChoiceOut:
    """Add a value to a list."""
    choice = choices.create_choice(
        db,
        context,
        list_name=body.list,
        value=body.value,
        label=body.label,
        sort=body.sort,
        active=body.active,
    )
    return shapes.choice_out(choice)


@choice_routes.patch("/{hid}")
def update_choice(
    hid: str, body: r.ChoicePatch, _: Inventory, context: Audit, db: Db
) -> r.ChoiceOut:
    """Change a choice's label or place, or stop offering it."""
    choice = choices.update_choice(db, context, hid, body.row_version, _changes(body))
    return shapes.choice_out(choice)


@choice_routes.delete("/{hid}", status_code=204)
def delete_choice(hid: str, _: Inventory, context: Audit, db: Db) -> None:
    """Remove a choice that no record holds. One in use can only be made inactive."""
    choices.delete_choice(db, context, hid)


# --- settings ------------------------------------------------------------------------


@setting_routes.get("")
def list_settings(_: Viewer, db: Db) -> list[r.SettingOut]:
    """List every setting with the value in force."""
    return [shapes.setting_out(setting) for setting in settings.list_settings(db)]


@setting_routes.put("/{key}")
def set_setting(key: str, body: r.SettingSet, _: Admin, context: Audit, db: Db) -> r.SettingOut:
    """Give a setting a value. Null returns it to its default."""
    setting = settings.set_setting(db, context, key, body.row_version, body.value)
    return shapes.setting_out(setting)


# --- lifecycle rules -----------------------------------------------------------------


@rule_routes.get("")
def list_rules(_: Viewer, db: Db) -> list[r.LifecycleRuleOut]:
    """List what each lifecycle state allows, in the order of the lifecycle."""
    return [shapes.rule_out(rule) for rule in lifecycle.list_rules(db)]


@rule_routes.patch("/{hid}")
def update_rule(
    hid: str, body: r.LifecycleRulePatch, _: Admin, context: Audit, db: Db
) -> r.LifecycleRuleOut:
    """Change what a state allows and where an item may move from it."""
    rule = lifecycle.update_rule(db, context, hid, body.row_version, _changes(body))
    return shapes.rule_out(rule)


ROUTERS = (tag_routes, choice_routes, setting_routes, rule_routes)
