// Putting text on the clipboard, when the text has first to be fetched.
//
// A browser lets a page write to the clipboard because of a click, and some stop
// honouring the click once the page has waited for an answer. So the clipboard is asked
// at once, with a promise of the text, where the browser can do that, and with the text
// itself afterwards where it cannot.

/** The browser would not take the text. It is carried here, to be shown for copying by hand. */
export class ClipboardRefused extends Error {
  readonly text: string;

  constructor(text: string) {
    super("The browser did not allow this page to write to the clipboard.");
    this.name = "ClipboardRefused";
    this.text = text;
  }
}

export interface ClipboardDeps {
  clipboard: Pick<Clipboard, "write" | "writeText"> | undefined;
  /** The browser's `ClipboardItem`, where it has one. */
  Item: (new (items: Record<string, Promise<Blob>>) => ClipboardItem) | undefined;
}

function browser(): ClipboardDeps {
  return {
    clipboard: globalThis.navigator?.clipboard,
    Item: typeof ClipboardItem === "undefined" ? undefined : ClipboardItem,
  };
}

/**
 * Put text that is on its way on the clipboard, and return it. A failure to fetch the
 * text is thrown as it is; a clipboard that refuses is a `ClipboardRefused`.
 */
export async function copyText(
  text: Promise<string>,
  deps: ClipboardDeps = browser(),
): Promise<string> {
  const { clipboard, Item } = deps;
  let early: Promise<void> | null = null;
  if (clipboard && Item && typeof clipboard.write === "function") {
    try {
      const blob = text.then((value) => new Blob([value], { type: "text/plain" }));
      early = clipboard.write([new Item({ "text/plain": blob })]);
      // What becomes of it is looked at below, once the text is known.
      early.catch(() => undefined);
    } catch {
      early = null;
    }
  }
  const value = await text;
  if (early) {
    try {
      await early;
      return value;
    } catch {
      // This browser does not take a promise of text: give it the text.
    }
  }
  try {
    if (!clipboard) throw new Error("no clipboard");
    await clipboard.writeText(value);
  } catch {
    throw new ClipboardRefused(value);
  }
  return value;
}
