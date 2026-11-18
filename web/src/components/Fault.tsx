// 0.9.7: a page that cannot be drawn says so, and offers to load again (P-230).

import { Component, type ErrorInfo, type ReactNode, useId, useMemo, useState } from "react";
import { copyText } from "../lib/clipboard";
import { faultText, isMissingPart, retryFailedParts } from "../lib/fault";
import { useSite } from "../lib/product";
import { BUILT_AS } from "../lib/version";
import { NewVersionNotice, versionStore } from "./NewVersion";

interface BoundaryProps {
  children: ReactNode;
  /** A change of it clears the fault: the address of the page beneath the menu bar. */
  resetKey?: string;
  /** Around the whole page, the frame with it: the fault page stands alone. */
  whole?: boolean;
}

interface BoundaryState {
  caught: boolean;
  error: unknown;
  componentStack: string | null;
  /**
   * The address the fault was caught at, once it is known: a move away from it clears
   * the fault. A fault caught in the very render that moved there is not cleared by it.
   */
  caughtAt: string | null;
}

const CLEAR: BoundaryState = { caught: false, error: null, componentStack: null, caughtAt: null };

/**
 * What stands where a page could not be drawn, or a part of it could not be fetched. The
 * fault is written to the console and sent nowhere; the server is asked what version it
 * runs, since a release installed meanwhile is a likely cause.
 */
export class FaultBoundary extends Component<BoundaryProps, BoundaryState> {
  override state: BoundaryState = CLEAR;

  static getDerivedStateFromError(error: unknown): Partial<BoundaryState> {
    return { caught: true, error, componentStack: null, caughtAt: null };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("The page could not be drawn:", error, info.componentStack ?? "");
    this.setState({
      componentStack: info.componentStack ?? null,
      caughtAt: this.props.resetKey ?? "",
    });
    void versionStore.check();
  }

  override componentDidMount(): void {
    // Around the whole page there is no menu bar: Back and Forward clear the fault.
    if (this.props.whole) window.addEventListener("popstate", this.clear);
  }

  override componentWillUnmount(): void {
    window.removeEventListener("popstate", this.clear);
  }

  override componentDidUpdate(): void {
    const { caught, caughtAt } = this.state;
    if (caught && caughtAt !== null && caughtAt !== (this.props.resetKey ?? "")) this.clear();
  }

  private readonly clear = (): void => {
    if (!this.state.caught) return;
    // A part that could not be fetched is fetched anew when it is next opened.
    retryFailedParts();
    this.setState(CLEAR);
  };

  override render(): ReactNode {
    if (!this.state.caught) return this.props.children;
    const page = <FaultPage error={this.state.error} componentStack={this.state.componentStack} />;
    if (!this.props.whole) return page;
    return (
      <main className="center fault-whole">
        <NewVersionNotice />
        {page}
      </main>
    );
  }
}

/** The address of the first page, under whatever prefix the page is served at. */
function firstPage(): string {
  return document.baseURI;
}

type Copied = "" | "done" | "refused";

function FaultPage({ error, componentStack }: { error: unknown; componentStack: string | null }) {
  const { productName } = useSite();
  const id = useId();
  const missing = isMissingPart(error);
  const text = useMemo(
    () =>
      faultText({
        error,
        componentStack,
        address: window.location.href,
        version: BUILT_AS,
        at: new Date(),
      }),
    [error, componentStack],
  );
  const [copied, setCopied] = useState<Copied>("");

  function copy() {
    copyText(Promise.resolve(text)).then(
      () => setCopied("done"),
      () => setCopied("refused"),
    );
  }

  return (
    <section className="fault" aria-labelledby={`${id}-title`} data-testid="fault">
      <h1 id={`${id}-title`}>This page could not be drawn</h1>
      <p role="alert">
        {missing
          ? "A part of the page could not be fetched. A new version may have been installed since the page was loaded."
          : "Something went wrong in the browser while it drew the page."}{" "}
        Load the page again. Where that does not help, give the text below to whoever looks after{" "}
        {productName}.
      </p>
      <p className="actions">
        <button type="button" onClick={() => window.location.reload()}>
          Load again
        </button>
        <a href={firstPage()}>The first page</a>
      </p>
      <h2 id={`${id}-text`}>The text of the fault</h2>
      {/* A box that is read, scrolled and selected by the keyboard as by the pointer. */}
      <textarea
        className="fault-text"
        readOnly
        rows={8}
        value={text}
        aria-labelledby={`${id}-text`}
        data-testid="fault-text"
      />
      <p className="actions">
        <button type="button" onClick={copy}>
          Copy the text
        </button>
        {copied === "done" && <span role="status">Copied.</span>}
        {copied === "refused" && (
          <span role="status">
            The browser would not copy it: select the text above and copy it.
          </span>
        )}
      </p>
    </section>
  );
}
