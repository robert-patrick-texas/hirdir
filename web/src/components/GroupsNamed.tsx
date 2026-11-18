import { Fragment } from "react";
import { Link } from "react-router";
import { api } from "../api";
import { plural } from "../lib/format";
import { queryBody } from "../lib/gridQuery";
import { groupTypeLabel } from "../lib/groups";
import { useLoad } from "../lib/hooks";
import { MOST_NAMED, namedBy } from "../lib/stacks";

/**
 * 0.9.6: the line above the items that says the words of the list name a device group,
 * with the group as a link and how many members it has (P-220). It is one small request
 * beside the list's own, which it does not hold back. The line is always there, empty
 * until something is found, and stands beside the heading: an answer that comes late
 * moves nothing the person is reading.
 */
export function GroupsNamed({ words }: { words: readonly string[] }) {
  const found = useLoad(`groups named ${JSON.stringify(words)}`, async (signal) => {
    const filter = namedBy(words);
    if (filter === null) return null;
    return api.request("post", "/api/v1/device-groups/query", {
      body: {
        ...queryBody({
          filter,
          sort: ["name"],
          limit: MOST_NAMED,
          offset: 0,
          include_archived: false,
          include_drafts: true,
        }),
        fields: ["name", "type", "member_count", "record_status"],
      },
      signal,
    });
  });
  // Words that are no longer those of the list name nothing, whatever was found for them.
  const groups = words.length > 0 ? (found.data?.items ?? []) : [];
  const more = words.length > 0 && found.data ? found.data.total - groups.length : 0;
  return (
    <p className="groups-named" role="status" data-testid="groups-named">
      {groups.length > 0 && (
        <>
          The words name{" "}
          {groups.map((group, index) => (
            <Fragment key={group.hid}>
              {index > 0 && "; "}
              the {groupTypeLabel(group.type).toLowerCase()}{" "}
              <Link to={`/groups/${encodeURIComponent(group.hid)}`}>{group.name}</Link>, with{" "}
              {plural(group.member_count ?? 0, "member")}
            </Fragment>
          ))}
          {more > 0 && `; and ${plural(more, "more group")}`}.
        </>
      )}
    </p>
  );
}
