import { describe, expect, it } from "vitest";
import { EVERY, whole } from "./whole";

/** A list of `total` records, read a page at a time as the server answers. */
function server(total: number) {
  const asked: number[] = [];
  const read = async (offset: number) => {
    asked.push(offset);
    const count = Math.max(0, Math.min(EVERY, total - offset));
    return { items: Array.from({ length: count }, (_, at) => offset + at), total };
  };
  return { asked, read };
}

describe("whole", () => {
  it("reads one page of a short list", async () => {
    const { asked, read } = server(12);
    expect(await whole(read)).toHaveLength(12);
    expect(asked).toEqual([0]);
  });

  it("reads past the first 1,000 to the last record", async () => {
    const { asked, read } = server(2 * EVERY + 5);
    const items = await whole(read);
    expect(items).toHaveLength(2 * EVERY + 5);
    expect(items.at(-1)).toBe(2 * EVERY + 4);
    expect(asked).toEqual([0, EVERY, 2 * EVERY]);
  });

  it("stops at a list of exactly 1,000", async () => {
    const { asked, read } = server(EVERY);
    expect(await whole(read)).toHaveLength(EVERY);
    expect(asked).toEqual([0]);
  });
});
