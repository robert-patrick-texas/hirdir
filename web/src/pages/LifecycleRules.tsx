import { useMemo, useState } from "react";
import { api, type Schemas } from "../api";
import { useAuth } from "../auth";
import { Notice, Problem } from "../components/Problem";
import { EditForm } from "../components/RecordForm";
import { AdminNav } from "../components/Shell";
import { SortTh } from "../components/SortTh";
import { useTitle } from "../lib/hooks";
import { DISPOSITIONS, type Rule, stateNames } from "../lib/lifecycle";
import { useRules } from "../lib/lists";
import type { FieldSpec } from "../lib/patch";
import { allows } from "../lib/roles";
import { useSorting } from "../lib/useSorting";

function listed(values: readonly string[]): string {
  return values.length > 0 ? values.join(", ") : "—";
}

function entryText(rule: Rule): string {
  const parts = [
    rule.entry_disposition ?? "",
    rule.entry_online === null ? "" : rule.entry_online ? "online" : "offline",
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "—";
}

/** What a cell is sorted by: its text, and nothing for the dash of an empty cell. */
function shown(text: string): string | null {
  return text === "—" ? null : text;
}

/** Admin → Lifecycle rules: what each of the nine states allows, and the moves between them. */
export function LifecycleRules() {
  useTitle("Lifecycle rules");
  const { user } = useAuth();
  const mayEdit = allows(user.role, "admin");
  const rules = useRules();
  const [editing, setEditing] = useState("");
  const [done, setDone] = useState("");
  const rows = rules.data ?? [];
  // With no header chosen the rules are in the order of the states, as the server sends them.
  const sorting = useSorting(rows, {
    state: (rule) => rule.state,
    dispositions: (rule) => shown(listed(rule.dispositions)),
    keeps_disposition: (rule) => rule.keeps_disposition,
    may_be_online: (rule) => shown(listed(rule.may_be_online)),
    must_be_online: (rule) => shown(listed(rule.must_be_online)),
    entry: (rule) => shown(entryText(rule)),
    next_states: (rule) => shown(listed(rule.next_states)),
  });
  const open = rows.find((rule) => rule.hid === editing) ?? null;

  return (
    <>
      <AdminNav />
      <h1>Lifecycle rules</h1>
      <p>
        One row for each state. The nine states are fixed; what a state allows, and where an item
        may move from it, can be changed by an Admin. An Admin may also force a move these rules do
        not list, with a reason.
      </p>
      <Problem error={rules.error} />
      <Notice text={done} />
      {rules.loading && !rules.data && <p role="status">Loading…</p>}
      {rules.data && (
        <div className="scroll">
          <table>
            <caption className="visually-hidden">
              The lifecycle rules, in the order of the states
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="state">
                  State
                </SortTh>
                <SortTh sort={sorting} column="dispositions">
                  Dispositions
                </SortTh>
                <SortTh sort={sorting} column="keeps_disposition">
                  Keeps disposition
                </SortTh>
                <SortTh sort={sorting} column="may_be_online">
                  May be online
                </SortTh>
                <SortTh sort={sorting} column="must_be_online">
                  Must be online
                </SortTh>
                <SortTh sort={sorting} column="entry">
                  Set on entry
                </SortTh>
                <SortTh sort={sorting} column="next_states">
                  May move to
                </SortTh>
                {mayEdit && (
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((rule) => (
                <tr key={rule.hid} data-state={rule.state}>
                  <th scope="row">{rule.state}</th>
                  <td>{listed(rule.dispositions)}</td>
                  <td>{rule.keeps_disposition ? "Yes" : "No"}</td>
                  <td>{listed(rule.may_be_online)}</td>
                  <td>{listed(rule.must_be_online)}</td>
                  <td>{entryText(rule)}</td>
                  <td>{listed(rule.next_states)}</td>
                  {mayEdit && (
                    <td>
                      <button
                        type="button"
                        onClick={() => {
                          setDone("");
                          setEditing(rule.hid);
                        }}
                        aria-label={`Edit the rule of ${rule.state}`}
                      >
                        Edit
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {mayEdit && open && (
        <RuleForm
          key={`${open.hid} ${open.row_version}`}
          rule={open}
          states={stateNames(rows)}
          onClose={() => setEditing("")}
          onSaved={() => {
            setDone(`The rule of ${open.state} was saved.`);
            setEditing("");
            rules.reload();
          }}
          onReload={rules.reload}
        />
      )}
    </>
  );
}

interface RuleFormProps {
  rule: Rule;
  states: readonly string[];
  onClose: () => void;
  onSaved: () => void;
  onReload: () => void;
}

function RuleForm({ rule, states, onClose, onSaved, onReload }: RuleFormProps) {
  const specs = useMemo<FieldSpec[]>(() => {
    const dispositions = DISPOSITIONS.map((name) => ({ value: name, label: name }));
    // Excess is always offline. That is decided, and not for a rule to change.
    const online = dispositions.filter((option) => option.value !== "Excess");
    return [
      {
        name: "dispositions",
        label: "Dispositions an item in this state may have",
        kind: "set",
        options: dispositions,
      },
      {
        name: "keeps_disposition",
        label: "An item keeps the disposition it came with",
        kind: "boolean",
        hint: "That disposition is then allowed as well",
      },
      {
        name: "may_be_online",
        label: "Dispositions that may be expected online",
        kind: "set",
        options: online,
      },
      {
        name: "must_be_online",
        label: "Dispositions that are always expected online",
        kind: "set",
        options: online,
        hint: "Each must be among those that may be online",
      },
      {
        name: "entry_disposition",
        label: "Disposition set on entry",
        kind: "choice",
        blank: "None",
        options: dispositions,
        hint: "Taken when the item's own is not allowed in this state",
      },
      {
        name: "entry_online",
        label: "Expected online on entry",
        kind: "tristate",
        blank: "Not set",
      },
      {
        name: "next_states",
        label: "States an item may move to from this one",
        kind: "set",
        options: states
          .filter((state) => state !== rule.state)
          .map((state) => ({ value: state, label: state })),
      },
    ];
  }, [states, rule.state]);

  return (
    <section className="panel" aria-labelledby="edit-rule">
      <h2 id="edit-rule">The rule of {rule.state}</h2>
      <EditForm<Rule, Schemas["LifecycleRulePatch"]>
        specs={specs}
        record={rule}
        save={(body) =>
          api.request("patch", "/api/v1/lifecycle-rules/{hid}", { path: { hid: rule.hid }, body })
        }
        onSaved={onSaved}
        onReload={onReload}
        submitLabel="Save rule"
      />
      <p className="actions">
        <button type="button" onClick={onClose}>
          Close
        </button>
      </p>
    </section>
  );
}
