// 0.9.6 (P-216): the line under the heading of a minor item: its type and model, its
// position in the item it is in, as a link, and its site; and a link to the spares of
// its model at that site. A major item has none: its page says the same in its facts.

import { Link } from "react-router";
import type { Schemas } from "../api";
import { itemName } from "../lib/format";
import { minorWhat, sparesPath } from "../lib/minor";
import { choiceLabel } from "../lib/options";

type Item = Schemas["ItemOut"];
type Choice = Schemas["ChoiceOut"];

export function MinorLine({
  item,
  choices,
}: {
  item: Item;
  choices: readonly Choice[] | undefined;
}) {
  if (item.is_major) return null;
  const what = minorWhat(item, choiceLabel(choices, "catalog_type", item.catalog?.type ?? null));
  const site = item.effective.location_hid.site;
  const spares = sparesPath(item);
  const { parent } = item;
  return (
    <p className="minor-line" data-testid="minor-line">
      {what && <span data-part="what">{what}</span>}
      {parent && (
        <span data-part="in">
          {what && " · "}
          {item.position ? `${item.position} in ` : "In "}
          <Link to={`/items/${encodeURIComponent(parent.hid)}`}>{itemName(parent)}</Link>
        </span>
      )}
      {site && (
        <span data-part="site">
          {(what || parent) && " · "}
          {site}
        </span>
      )}
      {spares && (
        <>
          {" "}
          <Link to={spares} className="here-link" data-testid="spares-here">
            Spares of this model here
          </Link>
        </>
      )}
    </p>
  );
}
