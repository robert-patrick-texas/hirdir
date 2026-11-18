// 0.9.6: a list a form offers whole is read to its end (P-200).

// The most rows the server lists at once.
export const EVERY = 1000;

/**
 * Every record of a list, read a page of the most the server lists at a time until the
 * last: a list a form offers whole leaves none out, past the first 1,000 (P-200).
 */
export async function whole<T>(
  read: (offset: number) => Promise<{ items: T[]; total: number }>,
): Promise<T[]> {
  const items: T[] = [];
  for (let offset = 0; ; offset += EVERY) {
    const page = await read(offset);
    items.push(...page.items);
    if (page.items.length < EVERY || items.length >= page.total) return items;
  }
}
