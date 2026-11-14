import type { Schemas } from "../api";
import type { SortColumns } from "../lib/sort";
import {
  amountText,
  type Counted,
  conditionLabel,
  countText,
  kindLabel,
  kindsShown,
  type ManagementMeasures,
  type Totals,
} from "../lib/summary";
import { useSorting } from "../lib/useSorting";
import { HealthCounts } from "./Health";
import { SortTh } from "./SortTh";

type Choice = Schemas["ChoiceOut"];

interface HeadlineTotalsProps {
  totals: Totals;
  /** The kinds the headline component count takes: the `count_kinds` setting, when known. */
  countKinds: readonly string[] | null;
}

/**
 * The headline of the summary, as the server counted it: the component count beside the
 * managed-node count, the support weight, the components by health in their colours, and
 * the kinds that stand beside the headline count. It holds no money: the estimated value
 * and the annual support cost are in the management report.
 */
export function HeadlineTotals({ totals, countKinds }: HeadlineTotalsProps) {
  const kinds = kindsShown(totals.by_kind, countKinds);
  // What the count takes first, as before, until a header is pressed. The entries with
  // no kind are a row like the others, and sort by what the row is called.
  const columns: SortColumns<Counted> = {
    kind: (kind) => kindLabel(kind.key),
    items: (kind) => kind.items,
    components: (kind) => kind.component_count,
    counted: (kind) => (kinds.counted.includes(kind) ? "Yes" : "No, beside it"),
  };
  const sorting = useSorting([...kinds.counted, ...kinds.beside], columns);
  return (
    <div data-testid="totals">
      <dl className="totals">
        <div>
          <dt>Components</dt>
          <dd data-testid="total-components">{countText(totals.component_count)}</dd>
        </div>
        <div>
          <dt>Managed nodes</dt>
          <dd data-testid="total-nodes">{countText(totals.managed_node_count)}</dd>
        </div>
        <div>
          <dt>Support weight</dt>
          <dd data-testid="total-weight">{amountText(totals.support_weight)}</dd>
        </div>
        <div>
          <dt>Items, major and minor</dt>
          <dd data-testid="total-items">{countText(totals.items)}</dd>
        </div>
      </dl>
      <h3>Components by health</h3>
      <HealthCounts counts={totals.by_health} />
      {totals.by_kind.length > 0 && (
        <div className="scroll">
          <table className="narrow" data-testid="totals-by-kind">
            <caption>
              {countKinds === null
                ? "By kind"
                : "By kind: what the component count takes, and what stands beside it"}
            </caption>
            <thead>
              <tr>
                <SortTh sort={sorting} column="kind">
                  Kind
                </SortTh>
                <SortTh sort={sorting} column="items" className="number">
                  Items
                </SortTh>
                <SortTh sort={sorting} column="components" className="number">
                  Components
                </SortTh>
                {countKinds !== null && (
                  <SortTh sort={sorting} column="counted">
                    In the component count
                  </SortTh>
                )}
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((kind) => (
                <tr key={kind.key ?? ""} data-kind={kind.key ?? ""}>
                  <th scope="row">{kindLabel(kind.key)}</th>
                  <td className="number">{countText(kind.items)}</td>
                  <td className="number">{countText(kind.component_count)}</td>
                  {countKinds !== null && (
                    <td>{kinds.counted.includes(kind) ? "Yes" : "No, beside it"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/** The components of each condition, and those of which nobody has said: on the summary's own page. */
export function ConditionTotals({
  conditions,
  choices,
}: {
  conditions: readonly Counted[];
  choices: readonly Choice[] | undefined;
}) {
  // The components of which nobody has said are a row like the others, and sort by what
  // the row is called.
  const sorting = useSorting(conditions, {
    condition: (condition) => conditionLabel(condition, choices),
    items: (condition) => condition.items,
    components: (condition) => condition.component_count,
  });
  return (
    <div className="scroll">
      <table className="narrow" data-testid="totals-by-condition">
        <caption>By condition: the state of the hardware, as people have recorded it</caption>
        <thead>
          <tr>
            <SortTh sort={sorting} column="condition">
              Condition
            </SortTh>
            <SortTh sort={sorting} column="items" className="number">
              Items
            </SortTh>
            <SortTh sort={sorting} column="components" className="number">
              Components
            </SortTh>
          </tr>
        </thead>
        <tbody>
          {sorting.rows.map((condition) => (
            <tr key={condition.key ?? ""} data-condition={condition.key ?? ""}>
              <th scope="row" className={condition.key === null ? "muted" : undefined}>
                {conditionLabel(condition, choices)}
              </th>
              <td className="number">{countText(condition.items)}</td>
              <td className="number">{countText(condition.component_count)}</td>
            </tr>
          ))}
          {conditions.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                No item is in view.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

interface ManagementTotalsProps {
  totals: ManagementMeasures;
  /** The installation's currency, a label only. */
  currency: string;
}

/**
 * The totals of the management report: the estimated value and the annual support cost
 * of the items in view, beside how many they are.
 */
export function ManagementTotals({ totals, currency }: ManagementTotalsProps) {
  const money = currency ? ` (${currency})` : "";
  return (
    <dl className="totals" data-testid="management-totals">
      <div>
        <dt>Estimated value{money}</dt>
        <dd data-testid="total-value">{amountText(totals.est_value)}</dd>
      </div>
      <div>
        <dt>Annual support cost{money}</dt>
        <dd data-testid="total-cost">{amountText(totals.annual_support_cost)}</dd>
      </div>
      <div>
        <dt>Components</dt>
        <dd data-testid="total-components">{countText(totals.component_count)}</dd>
      </div>
      <div>
        <dt>Items, major and minor</dt>
        <dd data-testid="total-items">{countText(totals.items)}</dd>
      </div>
    </dl>
  );
}
