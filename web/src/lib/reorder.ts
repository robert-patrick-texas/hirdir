// Moving a row of an ordered list a place up or down.
//
// A list is ordered by a number on each row. Rows may share a number, or sit one apart,
// so a move cannot always be made by swapping two of them: the whole list is given an
// order with room in it (10, 20, 30 …) with the two rows changing places, and only the
// rows whose number then differs are returned, to be written one by one.

interface Ordered {
  hid: string;
  sort: number;
  row_version: number;
}

export interface SortChange {
  hid: string;
  row_version: number;
  sort: number;
}

const STEP = 10;

/**
 * The changes that move the row `hid` by one place, `-1` for up and `1` for down.
 * `rows` are in the order shown. A move off either end changes nothing.
 */
export function reordered(rows: readonly Ordered[], hid: string, by: -1 | 1): SortChange[] {
  const from = rows.findIndex((row) => row.hid === hid);
  const to = from + by;
  if (from < 0 || to < 0 || to >= rows.length) return [];
  const order = [...rows];
  const [moved] = order.splice(from, 1);
  if (!moved) return [];
  order.splice(to, 0, moved);
  const changes: SortChange[] = [];
  order.forEach((row, place) => {
    const sort = (place + 1) * STEP;
    if (row.sort !== sort) changes.push({ hid: row.hid, row_version: row.row_version, sort });
  });
  return changes;
}
