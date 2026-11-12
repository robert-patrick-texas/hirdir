import { useEffect, useId, useRef, useState } from "react";

interface SecretBoxProps {
  /** What the secret is and whose, such as "Access code for vera". */
  title: string;
  secret: string;
  /** More to say, such as that the reader's own session has ended. */
  note?: string;
  onDone: () => void;
}

/**
 * A secret the server shows once: an access code or a service token. It is marked
 * plainly, can be copied, and is gone when dismissed.
 */
export function SecretBox({ title, secret, note, onDone }: SecretBoxProps) {
  const id = useId();
  const heading = useRef<HTMLHeadingElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [copied, setCopied] = useState("");

  // Bring the reader to the secret: it appears once and must not be missed.
  useEffect(() => {
    heading.current?.focus();
  }, []);

  async function copy() {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied("Copied to the clipboard.");
    } catch {
      // No clipboard access, as on a page not served over HTTPS: leave it selected.
      input.current?.focus();
      input.current?.select();
      setCopied("Could not copy. The text is selected: copy it with Ctrl+C.");
    }
  }

  return (
    <section className="secret" aria-labelledby={`${id}-title`} data-testid="secret-box">
      <h2 id={`${id}-title`} ref={heading} tabIndex={-1}>
        {title}
      </h2>
      <p className="secret-warning">
        <strong>Copy it now. It will not be shown again.</strong>
      </p>
      {note && <p>{note}</p>}
      <div className="secret-row">
        <label htmlFor={`${id}-value`}>Shown once</label>
        <input
          id={`${id}-value`}
          ref={input}
          className="mono"
          type="text"
          readOnly
          value={secret}
          size={Math.min(Math.max(secret.length + 2, 20), 70)}
          onFocus={(event) => event.target.select()}
        />
        <button type="button" onClick={copy}>
          Copy
        </button>
        <button type="button" onClick={onDone}>
          Done
        </button>
      </div>
      <p className="copied" role="status" aria-live="polite">
        {copied}
      </p>
    </section>
  );
}
