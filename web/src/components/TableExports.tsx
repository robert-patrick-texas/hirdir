// 0.9.13: the tables a file is taken for, each exported whole in one press, an empty one
// as the template of its import, and every table at once (P-286); and the three tables of
// Geography from the Geography page (P-287).

import { api } from "../api";
import { latestOf, type Saving, savedText, useSaving } from "../lib/download";
import { useLoad, useReloadOn } from "../lib/hooks";
import { useSite } from "../lib/product";
import {
  countWords,
  everythingName,
  exportLabel,
  type TableRow,
  tableRows,
  tablesText,
} from "../lib/tables";
import { type Entity, exportName, type FileFormat } from "../lib/transfer";
import { Problem } from "./Problem";

const FORMATS: readonly FileFormat[] = ["csv", "json"];

/** The key under which the export of a table, or of everything, is said. */
function keyOf(entity: Entity | "all", format: FileFormat): string {
  return `${entity} ${format}`;
}

function working(saving: Saving, key: string): boolean {
  const saved = saving.saved.get(key);
  return saved !== undefined && "working" in saved;
}

/**
 * What became of the export pressed last of some buttons, said beside them: under way,
 * saved, or refused, as by a busy server, after which the button may be pressed again.
 * Both parts are always in the page, so that a screen reader says what comes.
 */
function Said({ saving, keys }: { saving: Saving; keys: readonly string[] }) {
  const latest = latestOf(saving.saved, keys)?.saved;
  return (
    <div className="table-export-said">
      <span role="status">{savedText(latest)}</span>
      <Problem error={latest && "error" in latest ? latest.error : null} />
    </div>
  );
}

/** The two buttons that export one table whole, as CSV and as JSON. */
function ExportButtons({ row, saving }: { row: TableRow; saving: Saving }) {
  const { productName } = useSite();
  return (
    <span className="actions table-export-buttons">
      {FORMATS.map((format) => {
        const key = keyOf(row.entity, format);
        return (
          <button
            key={format}
            type="button"
            aria-label={exportLabel(row, format)}
            disabled={working(saving, key)}
            onClick={() =>
              void saving.save(
                key,
                // The whole table, as the zip of every table holds it: the server's word.
                () =>
                  api.download("/api/v1/exports", {
                    body: { entity: row.entity, format, whole: true },
                  }),
                exportName(row.entity, format, productName),
              )
            }
          >
            {format.toUpperCase()}
          </button>
        );
      })}
    </span>
  );
}

/**
 * The Import page's list of every table a file is taken for, in the order files are
 * loaded, each with how many records it holds and its export as CSV and as JSON; and the
 * export of every table at once, as one zip. The counts are read when the page opens and
 * again whenever `turn` changes, as after an import is applied. Every button works from
 * the start: until the list has come, the tables are those this build knows.
 */
export function TableExports({ turn }: { turn: number }) {
  const { productName } = useSite();
  const tables = useLoad("export tables", (signal) =>
    api.request("get", "/api/v1/exports/tables", { signal }),
  );
  useReloadOn(turn, tables.refresh);
  const saving = useSaving();
  const rows = tableRows(tables.data);
  const everything = FORMATS.map((format) => keyOf("all", format));

  return (
    <section className="panel table-exports" aria-labelledby="import-tables">
      <h2 id="import-tables">What can be loaded and exported</h2>
      <p className="hint" data-testid="export-tables-said">
        {tablesText(rows)}, in the order their files are loaded, each exported whole as its import
        reads it. A table that holds nothing gives its CSV template: its header row alone.
      </p>
      <div className="table-exports-all">
        <span className="table-exports-lead">Export everything</span>{" "}
        <span className="actions table-export-buttons">
          {FORMATS.map((format) => {
            const key = keyOf("all", format);
            return (
              <button
                key={format}
                type="button"
                aria-label={`Export everything as ${format.toUpperCase()}`}
                disabled={working(saving, key)}
                onClick={() =>
                  void saving.save(
                    key,
                    () => api.download("/api/v1/exports/all", { body: { format } }),
                    everythingName(format, productName),
                  )
                }
              >
                {format.toUpperCase()}
              </button>
            );
          })}
        </span>
        <Said saving={saving} keys={everything} />
      </div>
      <Problem error={tables.error} />
      <div className="scroll table-exports-list">
        <table data-testid="export-tables">
          <caption className="visually-hidden">
            Every table a file is taken for, in the order files are loaded, with how many records
            each holds
          </caption>
          <thead>
            <tr>
              <th scope="col">Records</th>
              <th scope="col" className="number">
                How many
              </th>
              <th scope="col">Export</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.entity} data-entity={row.entity} data-count={row.count ?? undefined}>
                <th scope="row">{row.label}</th>
                <td className="number" data-testid="table-count">
                  {countWords(row.count)}
                </td>
                <td>
                  <ExportButtons row={row} saving={saving} />
                  <Said saving={saving} keys={FORMATS.map((format) => keyOf(row.entity, format))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** The three tables of Geography, in the order their files are loaded. */
const GEOGRAPHY: readonly Entity[] = ["regions", "sites", "locations"];

/**
 * Geography's export: the regions, the sites and the locations, each as CSV and as JSON,
 * the very files of the Import page (P-287), whatever the page's view counts.
 */
export function GeographyExport() {
  const saving = useSaving();
  const rows = tableRows(undefined, GEOGRAPHY);
  const keys = rows.flatMap((row) => FORMATS.map((format) => keyOf(row.entity, format)));
  return (
    // Each button is named in full, as Export Sites as CSV: the line needs no name of its own.
    <div className="geography-export" data-testid="geography-export">
      <p className="geography-export-tables">
        <span className="geography-export-lead">Export</span>
        {rows.map((row) => (
          <span key={row.entity} className="geography-export-table">
            {row.label} <ExportButtons row={row} saving={saving} />
          </span>
        ))}
      </p>
      <p className="hint">
        Each the whole table, the retired and the drafts among them, in the columns its import
        reads, to be corrected and loaded back on the Import page. A table that holds nothing gives
        its CSV template: its header row alone.
      </p>
      <Said saving={saving} keys={keys} />
    </div>
  );
}
