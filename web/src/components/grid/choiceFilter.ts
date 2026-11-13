// The filter of a column whose values come from a list: a tick box for each value, and
// one for rows where the field is blank. It only says what is wanted. The server does
// the filtering; see lib/gridQuery.ts for what its model becomes.

import type { FilterDisplayComp, FilterDisplayParams } from "ag-grid-community";
import type { ChoiceModel } from "../../lib/gridQuery";
import type { Option } from "../../lib/patch";

type Params = FilterDisplayParams<unknown, unknown, ChoiceModel>;

let made = 0;

function optionsOf(params: Params): readonly Option[] {
  const given: unknown = params.colDef.filterParams;
  const options =
    typeof given === "object" && given !== null ? (given as { options?: unknown }).options : null;
  return Array.isArray(options) ? (options as Option[]) : [];
}

export class ChoiceFilter implements FilterDisplayComp<unknown, unknown, ChoiceModel> {
  private params: Params | null = null;
  private readonly gui = document.createElement("fieldset");
  private readonly boxes = new Map<string, HTMLInputElement>();
  private readonly blank = document.createElement("input");

  init(params: Params): void {
    this.params = params;
    this.gui.className = "choice-filter";
    const legend = document.createElement("legend");
    legend.className = "visually-hidden";
    legend.textContent = `Show rows where ${params.colDef.headerName ?? "the value"} is`;
    this.gui.append(legend);
    for (const option of optionsOf(params)) {
      const box = document.createElement("input");
      this.boxes.set(option.value, box);
      this.gui.append(this.row(box, option.label));
    }
    this.gui.append(this.row(this.blank, "(Blank)"));
    this.show(params.state.model ?? params.model);
  }

  getGui(): HTMLElement {
    return this.gui;
  }

  refresh(params: Params): boolean {
    this.params = params;
    this.show(params.state.model ?? params.model);
    return true;
  }

  afterGuiAttached(): void {
    const [first] = this.boxes.values();
    (first ?? this.blank).focus();
  }

  destroy(): void {
    this.params = null;
  }

  private row(box: HTMLInputElement, text: string): HTMLElement {
    made += 1;
    box.type = "checkbox";
    box.id = `choice-filter-${made}`;
    box.addEventListener("change", () => this.report());
    const label = document.createElement("label");
    label.htmlFor = box.id;
    // Text from the inventory is put in as text, never as HTML.
    label.textContent = text;
    const row = document.createElement("div");
    row.className = "choice-filter-row";
    row.append(box, label);
    return row;
  }

  private show(model: ChoiceModel | null): void {
    const values = new Set(model?.values ?? []);
    for (const [value, box] of this.boxes) box.checked = values.has(value);
    this.blank.checked = model?.blank === true;
  }

  private report(): void {
    const values = [...this.boxes].filter(([, box]) => box.checked).map(([value]) => value);
    const blank = this.blank.checked;
    const model: ChoiceModel | null =
      values.length === 0 && !blank ? null : { filterType: "choice", values, blank };
    // The Apply button of the filter sends it; until then this is only what is on show.
    this.params?.onStateChange({ model });
  }
}
