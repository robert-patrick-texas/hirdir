// What a record is on, drawn as a tree of boxes joined by lines (P-177): a box at the top,
// then a column for each kind of thing beneath it, each box with its counts, every count
// a link to the list of what it counts, and the exceptions within it marked. A column, and
// what is beneath a box, shows at most twenty boxes and a link to the rest.
//
// It is drawn in HTML, the lines by the stylesheet in the colours of the theme. The
// boxes are headings and lists, so that a screen reader reads the tree in its order and
// the keyboard reaches every count; the lines are for the eye alone. In a narrow window
// the drawing scrolls by itself, and the page does not.

import type { ReactNode } from "react";
import { Link } from "react-router";

/** The most boxes a column, or what is beneath a box, shows before a link to the rest. */
export const TREE_LIMIT = 20;

/** A count in a box: the number, what it counts, and the list of what it counts. */
export interface TreeCount {
  key: string;
  value: number;
  /** What is counted, after the number: `items from it`, `places beneath it`. */
  label: string;
  /** The list of what is counted, filtered to it; null where there is none. */
  href?: string | null;
}

/** A box of the tree, and what is beneath it. */
export interface TreeNode {
  key: string;
  /** What the box is of, small above its name: `site`, `stack`. */
  kind?: string;
  /** The record, as people call it; a node of its own, as an operator's mark, where given. */
  title: ReactNode;
  /** The page of the record, where the title is text. */
  href?: string | null;
  /** More about the record, beneath its name: the path of a place. */
  detail?: string;
  counts: readonly TreeCount[];
  /** What within it is someone else's: marked where it is more than nothing. */
  exceptions?: TreeCount | null;
  /** What is beneath it, each a box. */
  beneath?: readonly TreeNode[];
  /** How many more are beneath it than are listed, and where they are. */
  more?: TreeMore | null;
}

/** How many more there are than are shown, and the list of them. */
export interface TreeMore {
  count: number;
  /** What they are, for the link: `places`, `groups`. */
  noun: string;
  href?: string | null;
}

/** A column beneath the box at the top: one kind of thing. */
export interface TreeColumn {
  key: string;
  heading: string;
  nodes: readonly TreeNode[];
  more?: TreeMore | null;
  /** What the column says when it holds nothing. */
  empty: string;
}

/** A count, as a link to what it counts where there is one. */
function CountLink({ count }: { count: TreeCount }) {
  const text = (
    <>
      <strong>{count.value.toLocaleString("en-US")}</strong> {count.label}
    </>
  );
  return count.href ? <Link to={count.href}>{text}</Link> : <span>{text}</span>;
}

/** The first `limit` of a list, and how many more there are than are shown. */
export function firstOf<T>(
  nodes: readonly T[],
  more: TreeMore | null | undefined,
  limit: number = TREE_LIMIT,
): { shown: readonly T[]; more: TreeMore | null } {
  const shown = nodes.slice(0, limit);
  const left = nodes.length - shown.length + (more?.count ?? 0);
  if (left <= 0) return { shown, more: null };
  return { shown, more: { noun: more?.noun ?? "", href: more?.href ?? null, count: left } };
}

function More({ more }: { more: TreeMore }) {
  const text = `and ${more.count.toLocaleString("en-US")} more${more.noun ? ` ${more.noun}` : ""}`;
  return (
    <li className="tree-item tree-more" data-testid="tree-more" data-more={more.count}>
      {more.href ? <Link to={more.href}>{text}</Link> : <span className="muted">{text}</span>}
    </li>
  );
}

function Box({ node, root = false }: { node: TreeNode; root?: boolean }) {
  const exceptions = node.exceptions && node.exceptions.value > 0 ? node.exceptions : null;
  const classes = ["tree-box", root ? "tree-root" : "", exceptions ? "tree-has-exceptions" : ""]
    .filter(Boolean)
    .join(" ");
  return (
    <div className={classes} data-testid={root ? "tree-root" : "tree-box"} data-key={node.key}>
      {node.kind && <span className="tree-kind">{node.kind}</span>}
      <span className="tree-title">
        {typeof node.title === "string" && node.href ? (
          <Link to={node.href}>{node.title}</Link>
        ) : (
          node.title
        )}
      </span>
      {node.detail && <span className="tree-detail">{node.detail}</span>}
      {node.counts.length > 0 && (
        <ul className="tree-counts">
          {node.counts.map((count) => (
            <li key={count.key} data-count={count.key} data-value={count.value}>
              <CountLink count={count} />
            </li>
          ))}
        </ul>
      )}
      {exceptions && (
        <p className="tree-exceptions" data-testid="tree-exceptions" data-value={exceptions.value}>
          <span className="tree-mark" aria-hidden="true">
            !
          </span>{" "}
          <CountLink count={exceptions} />
        </p>
      )}
    </div>
  );
}

function Item({ node, limit }: { node: TreeNode; limit: number }) {
  const beneath = firstOf(node.beneath ?? [], node.more, limit);
  return (
    <li className="tree-item">
      <Box node={node} />
      {(beneath.shown.length > 0 || beneath.more) && (
        <ul className="tree-boxes tree-beneath">
          {beneath.shown.map((child) => (
            <Item key={child.key} node={child} limit={limit} />
          ))}
          {beneath.more && <More more={beneath.more} />}
        </ul>
      )}
    </li>
  );
}

interface BoxTreeProps {
  /** What the drawing is of, for a screen reader: `What Op2 is on`. */
  label: string;
  root: TreeNode;
  columns: readonly TreeColumn[];
  /** The level of the headings of the columns: beneath the heading of the section. */
  level?: 3 | 4;
  /** The most boxes shown in a column, or beneath a box, before a link to the rest. */
  limit?: number;
  testId?: string;
}

/** The tree: the box at the top, joined by lines to a column of boxes for each kind. */
export function BoxTree({
  label,
  root,
  columns,
  level = 3,
  limit = TREE_LIMIT,
  testId,
}: BoxTreeProps) {
  const Heading = level === 3 ? "h3" : "h4";
  return (
    <figure className="tree" aria-label={label} data-testid={testId}>
      <div className="tree-scroll">
        <Box node={root} root />
        <div className="tree-trunk" aria-hidden="true" />
        <ul className="tree-columns">
          {columns.map((column) => {
            const { shown, more } = firstOf(column.nodes, column.more, limit);
            return (
              <li
                key={column.key}
                className="tree-column"
                data-column={column.key}
                data-testid="tree-column"
              >
                <Heading className="tree-head">{column.heading}</Heading>
                {shown.length === 0 && !more ? (
                  <p className="tree-empty muted">{column.empty}</p>
                ) : (
                  <ul className="tree-boxes">
                    {shown.map((node) => (
                      <Item key={node.key} node={node} limit={limit} />
                    ))}
                    {more && <More more={more} />}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </figure>
  );
}
