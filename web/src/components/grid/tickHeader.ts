// 0.9.7: the box in the heading of the column of boxes (P-233). It ticks the rows the grid
// has read from the server so far, and clears them. AG Grid offers a box of its own there
// only for rows it holds whole, not for rows read a block at a time as these are, so it
// is drawn here. It shows itself ticked only when every row of the list is read and
// ticked; with part of the list read, as the first 100 of 260, it shows the half mark,
// and its name says how many rows it takes. "All that match the filter" stays a button of
// its own, since it is a count sent as the filter and never a list of rows.

import type { GridApi, IHeaderComp, IHeaderParams, IRowNode } from "ag-grid-community";
import { tickName, tickState } from "../../lib/selection";

/** What the grid gives the box besides its own parameters: how many rows the list holds. */
export interface TickHeaderParams {
  total: () => number | null;
}

/** The rows read so far: not the places of rows still to come. */
function rowsRead(api: GridApi): IRowNode[] {
  const rows: IRowNode[] = [];
  api.forEachNode((node) => {
    if (node.data !== undefined) rows.push(node);
  });
  return rows;
}

export class TickHeader implements IHeaderComp {
  private box: HTMLInputElement = document.createElement("input");
  private gui: HTMLElement = document.createElement("span");
  private api: GridApi | null = null;
  private cell: HTMLElement | null = null;
  private total: () => number | null = () => null;

  private readonly update = () => {
    const api = this.api;
    if (!api || api.isDestroyed()) return;
    const rows = rowsRead(api);
    const ticked = rows.filter((node) => node.isSelected()).length;
    const state = tickState(rows.length, ticked, this.total());
    this.box.checked = state === "all";
    this.box.indeterminate = state === "some";
    this.box.disabled = rows.length === 0;
    const name = tickName(rows.length, rows.length > 0 && ticked === rows.length);
    this.box.setAttribute("aria-label", name);
    this.box.title = name;
  };

  private readonly toggle = () => {
    const api = this.api;
    if (!api || api.isDestroyed()) return;
    const rows = rowsRead(api);
    const every = rows.length > 0 && rows.every((node) => node.isSelected());
    if (every) api.deselectAll();
    else api.setNodesSelected({ nodes: rows, newValue: true });
    this.update();
  };

  private readonly onKey = (event: KeyboardEvent) => {
    // The grid moves the keyboard to the heading's cell, not to the box in it.
    if (event.key !== " " || event.target === this.box) return;
    event.preventDefault();
    this.toggle();
  };

  init(params: IHeaderParams & Partial<TickHeaderParams>): void {
    this.api = params.api;
    this.cell = params.eGridHeader;
    if (params.total) this.total = params.total;
    this.gui.className = "grid-tick-all";
    this.box.type = "checkbox";
    this.box.setAttribute("data-testid", "grid-tick-all");
    this.box.addEventListener("change", this.toggle);
    this.gui.append(this.box);
    this.cell.addEventListener("keydown", this.onKey);
    params.api.addEventListener("selectionChanged", this.update);
    params.api.addEventListener("modelUpdated", this.update);
    this.update();
  }

  getGui(): HTMLElement {
    return this.gui;
  }

  refresh(): boolean {
    this.update();
    return true;
  }

  destroy(): void {
    this.box.removeEventListener("change", this.toggle);
    this.cell?.removeEventListener("keydown", this.onKey);
    const api = this.api;
    if (api && !api.isDestroyed()) {
      api.removeEventListener("selectionChanged", this.update);
      api.removeEventListener("modelUpdated", this.update);
    }
    this.api = null;
  }
}
