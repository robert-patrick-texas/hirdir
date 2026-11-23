// What a page's live regions said, as a reader of the screen would hear it (0.9.19, the
// review of P-325): each time the words of a region change to words, the region's
// politeness and its words, and whether the region came onto the page already holding
// them, which no reader hears. Listened for from the first script of every page of the
// context, so that what a page says as it opens is caught too.

import type { BrowserContext, Page } from "@playwright/test";

export interface Heard {
  live: string;
  text: string;
  /** The region came holding these words: nothing was heard. */
  came: boolean;
  testId: string;
}

/** Listen on every page of the context, from its first script. */
export async function listen(context: BrowserContext): Promise<void> {
  await context.addInitScript(() => {
    const heard: Array<{ live: string; text: string; came: boolean; testId: string }> = [];
    const gone = { jobs: 0 };
    const world = window as unknown as { __heard: typeof heard; __gone: typeof gone };
    world.__heard = heard;
    world.__gone = gone;
    const last = new WeakMap<Element, string>();
    let jobs = false;
    const look = () => {
      for (const region of document.querySelectorAll(
        '[aria-live], [role="status"], [role="alert"]',
      )) {
        const text = (region.textContent ?? "").replace(/\s+/g, " ").trim();
        const had = last.get(region);
        if (had === text) continue;
        last.set(region, text);
        if (text === "") continue;
        const live =
          region.getAttribute("aria-live") ??
          (region.getAttribute("role") === "alert" ? "assertive" : "polite");
        heard.push({
          live,
          text,
          came: had === undefined,
          testId: (region as HTMLElement).dataset.testid ?? "",
        });
      }
      // The table of past imports, once there: whether it went away for a moment.
      const table = document.querySelector('[data-testid="import-jobs"]') !== null;
      if (jobs && !table) gone.jobs += 1;
      jobs = table;
    };
    new MutationObserver(look).observe(document, {
      subtree: true,
      childList: true,
      characterData: true,
    });
  });
}

/** What the page has said so far, and how often the past imports went away. */
export async function heardOn(page: Page): Promise<{ heard: Heard[]; jobsGone: number }> {
  return page.evaluate(() => {
    const world = window as unknown as { __heard: Heard[]; __gone: { jobs: number } };
    return { heard: [...world.__heard], jobsGone: world.__gone.jobs };
  });
}

/** The words a region of a test id said, in order, those heard alone. */
export function said(heard: readonly Heard[], testId: string): string[] {
  return heard.filter((one) => one.testId === testId && !one.came).map((one) => one.text);
}
