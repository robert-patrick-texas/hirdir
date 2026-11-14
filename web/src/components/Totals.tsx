import type { Schemas } from "../api";
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
import { HealthCounts } from "./Health";

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
                <th scope="col">Kind</th>
                <th scope="col" className="number">
                  Items
                </th>
                <th scope="col" className="number">
                  Components
                </th>
                {countKinds !== null && <th scope="col">In the component count</th>}
              </tr>
            </thead>
            <tbody>
              {[...kinds.counted, ...kinds.beside].map((kind) => (
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
  return (
    <div className="scroll">
      <table className="narrow" data-testid="totals-by-condition">
        <caption>By condition: the state of the hardware, as people have recorded it</caption>
        <thead>
          <tr>
            <th scope="col">Condition</th>
            <th scope="col" className="number">
              Items
            </th>
            <th scope="col" className="number">
              Components
            </th>
          </tr>
        </thead>
        <tbody>
          {conditions.map((condition) => (
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
