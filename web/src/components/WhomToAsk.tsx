// 0.9.2: whom to ask, the team that runs this installation (P-169), as About and the
// sign-in page list them: each that is set, and none that is not. The address on the web
// opens in a new tab, as a link of a record does, and gives the page it opens nothing of
// this one's.

import { isWebAddress } from "../lib/links";
import { type Help, mailtoHref, telHref } from "../lib/product";

export function HelpList({ help }: { help: Help }) {
  const { organization, email, phone, url } = help;
  const dial = phone === null ? null : telHref(phone);
  return (
    <dl className="facts help-list" data-testid="whom-to-ask">
      {organization !== null && (
        <>
          <dt>Organization</dt>
          <dd data-testid="help-organization">{organization}</dd>
        </>
      )}
      {email !== null && (
        <>
          <dt>Email</dt>
          <dd data-testid="help-email">
            <a href={mailtoHref(email)}>{email}</a>
          </dd>
        </>
      )}
      {phone !== null && (
        <>
          <dt>Phone</dt>
          <dd data-testid="help-phone">{dial === null ? phone : <a href={dial}>{phone}</a>}</dd>
        </>
      )}
      {url !== null && (
        <>
          <dt>On the web</dt>
          <dd data-testid="help-url">
            {isWebAddress(url) ? (
              <a href={url} target="_blank" rel="noopener noreferrer">
                {url}
              </a>
            ) : (
              url
            )}
          </dd>
        </>
      )}
    </dl>
  );
}
