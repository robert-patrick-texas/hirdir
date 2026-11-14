import { amountText, countText, kindLabel, kindsShown, type Totals } from "../lib/summary";

interface HeadlineTotalsProps {
  totals: Totals;
  /** The kinds the headline component count takes: the `count_kinds` setting, when known. */
  countKinds: readonly string[] | null;
  /** The installation's currency, a label only. */
  currency: string;
}

/**
 * The totals of a view of the items, as the server counted them: the component count
 * beside the managed-node count, the support weight, the estimated value and the annual
 * support cost, and the kinds that stand beside the headline count.
 */
export function HeadlineTotals({ totals, countKinds, currency }: HeadlineTotalsProps) {
  const kinds = kindsShown(totals.by_kind, countKinds);
  const money = currency ? ` (${currency})` : "";
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
          <dt>Estimated value{money}</dt>
          <dd data-testid="total-value">{amountText(totals.est_value)}</dd>
        </div>
        <div>
          <dt>Annual support cost{money}</dt>
          <dd data-testid="total-cost">{amountText(totals.annual_support_cost)}</dd>
        </div>
        <div>
          <dt>Items, major and minor</dt>
          <dd data-testid="total-items">{countText(totals.items)}</dd>
        </div>
      </dl>
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
                <tr key={kind.kind} data-kind={kind.kind}>
                  <th scope="row">{kindLabel(kind.kind)}</th>
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
