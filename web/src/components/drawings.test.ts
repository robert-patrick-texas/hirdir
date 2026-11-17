// The drawings of 0.9.4, rendered: the walk of a value as a row of boxes joined by
// arrows (P-176), and what a record is on as a tree of boxes joined by lines (P-177).
// Every name here is invented, as the examples of the documentation are.

import { createElement, type ReactElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { BoxTree, firstOf, TREE_LIMIT, type TreeNode } from "./BoxTree";
import { BoxWalk, STATE_WORDS, Walk, type WalkBox, WalkTable } from "./BoxWalk";

function html(element: ReactElement): string {
  return renderToStaticMarkup(createElement(MemoryRouter, null, element));
}

/** A link to `href` whose text is `inner`, as the router writes it. */
function link(href: string, inner: string): RegExp {
  const literal = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`<a href="${literal(href)}"[^>]*>${literal(inner)}</a>`);
}

/** The markup of each part that begins with `marker`, up to the next of them. */
function parts(markup: string, marker: string): string[] {
  return markup.split(marker).slice(1);
}

// An access point in the controller domain east-wlc and the custom group lobby-aps: the
// domain ranks first and decides, the custom group is passed over, and it has none of
// its own.
const steps: WalkBox[] = [
  { key: "own", kind: "Its own", title: "ap-lobby-01", value: null, state: "nothing" },
  {
    key: "g1",
    kind: "Group · controller domain · 1st",
    title: "east-wlc",
    href: "/groups/0193a1f4-0000-7000-8000-00000000d001",
    value: "LM",
    state: "decides",
  },
  {
    key: "g2",
    kind: "Group · custom · 2nd",
    title: "lobby-aps",
    href: "/groups/0193a1f4-0000-7000-8000-00000000d002",
    value: "Op2",
    via: { text: "all-aps", href: "/groups/0193a1f4-0000-7000-8000-00000000d003" },
    state: "passed_over",
  },
  { key: "site", kind: "Site", title: "Example Campus", value: "Op3", state: "retired" },
];

describe("the walk of a value as a row of boxes", () => {
  const markup = html(createElement(BoxWalk, { label: "Operator", steps }));
  const boxes = parts(markup, '<li class="walk-step"');

  it("has one box for each step, in the order of the walk, as an ordered list", () => {
    expect(markup).toContain(
      '<ol class="walk-row" aria-label="The walk of Operator, in its order"',
    );
    expect(boxes).toHaveLength(4);
    expect(boxes.map((box) => /data-step="(\d+)"/.exec(box)?.[1])).toEqual(["1", "2", "3", "4"]);
    expect(boxes[1]).toContain("east-wlc");
    expect(boxes[2]).toContain("lobby-aps");
  });

  it("draws the step that decides in the accent, and no other", () => {
    const deciding = boxes.filter((box) => box.includes("walk-box walk-decides"));
    expect(deciding).toHaveLength(1);
    expect(deciding[0]).toContain("east-wlc");
    expect(deciding[0]).toContain(">decides<");
    expect(deciding[0]).not.toContain("<s>");
  });

  it("strikes through the value of a step passed over, and of one passed over as retired", () => {
    expect(boxes[2]).toContain("walk-box walk-passed_over");
    expect(boxes[2]).toContain("<s>Op2</s>");
    expect(boxes[2]).toContain(">passed over<");
    expect(boxes[3]).toContain("walk-box walk-retired");
    expect(boxes[3]).toContain("<s>Op3</s>");
    expect(boxes[3]).toContain(">retired, passed over<");
  });

  it("draws a step that holds nothing dashed, and says so in words", () => {
    expect(boxes[0]).toContain("walk-box walk-nothing");
    // Once: no value line of "nothing" beside the state that says it.
    expect(boxes[0]).not.toContain("walk-value");
    expect(boxes[0]).toContain(">holds nothing<");
  });

  it("links each record that has a page, and the group a value is had from", () => {
    expect(boxes[1]).toContain('href="/groups/0193a1f4-0000-7000-8000-00000000d001"');
    expect(boxes[2]).toContain('href="/groups/0193a1f4-0000-7000-8000-00000000d003"');
    expect(boxes[2]).toContain("from <a");
    expect(boxes[0]).not.toContain("<a ");
  });

  it("joins the boxes by arrows that a screen reader does not read, one fewer than the boxes", () => {
    const arrows = markup.match(/class="walk-arrow" aria-hidden="true"/g) ?? [];
    expect(arrows).toHaveLength(3);
    expect(boxes[0]).not.toContain("walk-arrow");
  });

  it("says what a value of its own overrides, where it is given", () => {
    expect(markup).not.toContain("walk-overrides");
    const own = html(
      createElement(BoxWalk, {
        label: "Location",
        steps: [{ key: "own", kind: "Its own", title: "sw-01", value: "Rack 4", state: "decides" }],
        overrides: "Room 2, from stack-a",
      }),
    );
    expect(own).toContain('data-testid="walk-overrides"');
    expect(own).toContain("Overrides</span> Room 2, from stack-a");
  });
});

describe("the walk of a value as a table", () => {
  const markup = html(createElement(WalkTable, { label: "Operator", steps }));
  const rows = parts(markup, "<tr data-state=");

  it("has the same steps as the boxes, in their order, with what each is in words", () => {
    expect(markup).toContain("The walk of Operator, as a table");
    expect(rows).toHaveLength(4);
    expect(rows.map((row) => /^"([a-z_]+)"/.exec(row)?.[1])).toEqual([
      "nothing",
      "decides",
      "passed_over",
      "retired",
    ]);
    for (const [place, step] of steps.entries()) {
      expect(rows[place]).toContain(STATE_WORDS[step.state]);
    }
    expect(rows[1]).toContain("walk-decides-word");
  });

  it("writes a value passed over as it is, to copy", () => {
    expect(rows[2]).toContain("Op2");
    expect(rows[2]).not.toContain("<s>");
  });
});

describe("a walk with its table", () => {
  it("folds the table until it is asked for, unless the page opens it", () => {
    const folded = html(createElement(Walk, { label: "Owner", steps }));
    expect(folded).toContain('<details class="walk-as-table">');
    expect(folded).toContain("As a table");
    const open = html(createElement(Walk, { label: "Owner", steps, tableOpen: true }));
    expect(open).toContain('<details class="walk-as-table" open="">');
  });
});

const place = (number: number, more: Partial<TreeNode> = {}): TreeNode => ({
  key: `p${number}`,
  kind: "location",
  title: `Room ${number}`,
  href: `/geography/locations/p${number}`,
  counts: [{ key: "items", value: number, label: "items from it", href: `/items?n=${number}` }],
  ...more,
});

describe("what a record is on as a tree of boxes", () => {
  const root: TreeNode = {
    key: "op",
    kind: "operator",
    title: "Op2",
    href: "/operators/op",
    counts: [{ key: "items", value: 42, label: "items in all", href: "/items?op=op" }],
  };
  const markup = html(
    createElement(BoxTree, {
      label: "What Op2 is on",
      root,
      columns: [
        {
          key: "places",
          heading: "Places given it",
          nodes: [
            place(1, {
              exceptions: { key: "exceptions", value: 2, label: "exceptions", href: "/items?x=1" },
              beneath: Array.from({ length: 25 }, (_, number) => place(100 + number)),
              more: { count: 5, noun: "places", href: "/geography" },
            }),
            place(2, { exceptions: { key: "exceptions", value: 0, label: "exceptions" } }),
          ],
          empty: "No place is given it.",
        },
        { key: "groups", heading: "Groups given it", nodes: [], empty: "No group is given it." },
        {
          key: "own",
          heading: "Its own items",
          nodes: Array.from({ length: 23 }, (_, number) => place(200 + number)),
          more: { count: 0, noun: "items", href: "/items?own=1" },
          empty: "No item is given it.",
        },
      ],
    }),
  );

  it("is a figure named for what it shows, with the box at the top first", () => {
    expect(markup).toMatch(/^<figure class="tree" aria-label="What Op2 is on"/);
    expect(markup.indexOf('data-testid="tree-root"')).toBeLessThan(
      markup.indexOf('data-testid="tree-column"'),
    );
    expect(markup).toContain('href="/operators/op"');
  });

  it("has a column for each kind, each under a heading, and says when one holds nothing", () => {
    const columns = parts(markup, 'data-testid="tree-column"');
    expect(columns).toHaveLength(3);
    expect(columns[0]).toContain('<h3 class="tree-head">Places given it</h3>');
    expect(columns[1]).toContain("No group is given it.");
  });

  it("makes every count a link to what it counts", () => {
    expect(markup).toMatch(link("/items?op=op", "<strong>42</strong> items in all"));
    expect(markup).toMatch(link("/items?n=1", "<strong>1</strong> items from it"));
  });

  it("marks a box with exceptions, and only where there are some", () => {
    const marked = markup.match(/data-testid="tree-exceptions"/g) ?? [];
    expect(marked).toHaveLength(1);
    expect(markup).toMatch(link("/items?x=1", "<strong>2</strong> exceptions"));
    expect(markup).toContain("tree-box tree-has-exceptions");
  });

  it("shows at most twenty in a column and beneath a box, with a link to the rest", () => {
    expect(TREE_LIMIT).toBe(20);
    const columns = parts(markup, 'data-testid="tree-column"');
    // The own items: 23 listed, 20 shown, a link to the 3 more.
    const own = columns[2] ?? "";
    expect(own.match(/data-testid="tree-box"/g) ?? []).toHaveLength(20);
    expect(own).toContain('data-more="3"');
    expect(own).toMatch(link("/items?own=1", "and 3 more items"));
    // Beneath the first place: 25 listed and 5 more the server did not send, 20 shown.
    expect(columns[0]).toContain('data-more="10"');
    expect(columns[0]).toMatch(link("/geography", "and 10 more places"));
  });

  it("draws its lines in the stylesheet, where a screen reader does not read them", () => {
    expect(markup).toContain('<div class="tree-trunk" aria-hidden="true"></div>');
    expect(markup).not.toContain("<svg");
  });

  it("takes the level of its headings from the page", () => {
    const deeper = html(
      createElement(BoxTree, {
        label: "x",
        root,
        level: 4,
        columns: [{ key: "a", heading: "A", nodes: [], empty: "None." }],
      }),
    );
    expect(deeper).toContain('<h4 class="tree-head">A</h4>');
  });
});

describe("the first of a list, and how many more", () => {
  it("is all of a short list, and nothing more", () => {
    expect(firstOf([1, 2, 3], null)).toEqual({ shown: [1, 2, 3], more: null });
  });

  it("is the first twenty of a long list, and the rest counted with those not sent", () => {
    const { shown, more } = firstOf(
      Array.from({ length: 22 }, (_, n) => n),
      { count: 4, noun: "groups", href: "/g" },
    );
    expect(shown).toHaveLength(20);
    expect(more).toEqual({ count: 6, noun: "groups", href: "/g" });
  });
});
