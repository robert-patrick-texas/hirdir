import { describe, expect, it, vi } from "vitest";
import { type ClipboardDeps, ClipboardRefused, copyText } from "./clipboard";

class Item {
  readonly items: Record<string, Promise<Blob>>;

  constructor(items: Record<string, Promise<Blob>>) {
    this.items = items;
  }
}

function deps(clipboard: Partial<Pick<Clipboard, "write" | "writeText">> | undefined) {
  return {
    clipboard: clipboard as ClipboardDeps["clipboard"],
    Item: Item as unknown as ClipboardDeps["Item"],
  };
}

describe("copyText", () => {
  it("asks for the clipboard at once, with a promise of the text", async () => {
    let release: (text: string) => void = () => undefined;
    const text = new Promise<string>((resolve) => {
      release = resolve;
    });
    const written: string[] = [];
    const write = vi.fn(async (items: ClipboardItem[]) => {
      const [item] = items as unknown as Item[];
      const blob = await item?.items["text/plain"];
      written.push((await blob?.text()) ?? "");
    });
    const writeText = vi.fn();
    const copying = copyText(text, deps({ write, writeText }));
    // The clipboard was asked before the text had arrived.
    expect(write).toHaveBeenCalledTimes(1);
    release("hid\tname");
    await expect(copying).resolves.toBe("hid\tname");
    expect(written).toEqual(["hid\tname"]);
    expect(writeText).not.toHaveBeenCalled();
  });

  it("gives the text itself to a browser that takes no promise", async () => {
    const write = vi.fn(async () => {
      throw new TypeError("not supported");
    });
    const writeText = vi.fn(async () => undefined);
    await expect(copyText(Promise.resolve("a\tb"), deps({ write, writeText }))).resolves.toBe(
      "a\tb",
    );
    expect(writeText).toHaveBeenCalledWith("a\tb");
  });

  it("uses writeText where there is no ClipboardItem", async () => {
    const writeText = vi.fn(async () => undefined);
    const clipboard = { writeText } as unknown as ClipboardDeps["clipboard"];
    await copyText(Promise.resolve("x"), { clipboard, Item: undefined });
    expect(writeText).toHaveBeenCalledWith("x");
  });

  it("hands back the text when the clipboard refuses, to be copied by hand", async () => {
    const refuse = vi.fn(async () => {
      throw new DOMException("denied", "NotAllowedError");
    });
    const failed = copyText(
      Promise.resolve("hid\ni-1"),
      deps({ write: refuse, writeText: refuse }),
    );
    await expect(failed).rejects.toBeInstanceOf(ClipboardRefused);
    await expect(failed).rejects.toMatchObject({ text: "hid\ni-1" });
  });

  it("hands back the text where there is no clipboard at all, as on a page without HTTPS", async () => {
    await expect(copyText(Promise.resolve("x"), deps(undefined))).rejects.toMatchObject({
      name: "ClipboardRefused",
      text: "x",
    });
  });

  it("throws the failure to fetch the text as it is, and writes nothing", async () => {
    const failure = new Error("the export was refused");
    const write = vi.fn(async (items: ClipboardItem[]) => {
      await (items as unknown as Item[])[0]?.items["text/plain"];
    });
    const writeText = vi.fn();
    await expect(copyText(Promise.reject(failure), deps({ write, writeText }))).rejects.toBe(
      failure,
    );
    expect(writeText).not.toHaveBeenCalled();
  });
});
