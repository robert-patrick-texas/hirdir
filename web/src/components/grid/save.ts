// Saving a file the page holds in memory.
//
// An export is fetched with the bearer token, as everything is, so the browser cannot
// be sent to it with a plain link: there is no cookie to let it in. The file is fetched
// first and then handed to the browser to save, through a link to the copy in memory.

// How long the copy in memory is kept for the browser to start saving it, in milliseconds.
const KEEP_FOR = 60_000;

/** Have the browser save a file under a name, as it saves any download. */
export function saveFile(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.hidden = true;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), KEEP_FOR);
}
