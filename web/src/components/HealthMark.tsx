// The health of the server in the menu bar of every page (P-270, P-272): a mark that is
// green, yellow, orange or red, each with a shape of its own, a circle, a triangle, a
// diamond and a square, so that they are told apart without the colour, and with its
// words for whoever points at it or has the page read aloud. It leads to About, where
// the measures are.
//
// It asks the server nothing: it shows what the newest answer the page got said, in the
// header every answer carries, which the API client hands to `serverHealth`. It is told
// only when the word or what is refused is another, so an answer that says the same
// draws nothing, and a change draws the mark and nothing else of the page.

import { useSyncExternalStore } from "react";
import { Link } from "react-router";
import { type Health, healthTitle, healthWords, serverHealth } from "../lib/serverHealth";

/** The shape of each health, in a box of 14 by 14. */
function Shape({ health }: { health: Health }) {
  switch (health) {
    case "good":
      return <circle cx="7" cy="7" r="5.5" />;
    case "slow":
      return <polygon points="7,1.2 13,12.4 1,12.4" />;
    case "very_slow":
      return <polygon points="7,0.8 13.2,7 7,13.2 0.8,7" />;
    default:
      return <rect x="1.5" y="1.5" width="11" height="11" />;
  }
}

/**
 * The shape and the colour of a health, without its words: beside words that say it,
 * as the name of a band of time on About, or within the mark of the menu bar.
 */
export function HealthShape({ health }: { health: Health }) {
  return (
    <svg
      className={`health-shape health-${health}`}
      viewBox="0 0 14 14"
      width="14"
      height="14"
      focusable="false"
      aria-hidden="true"
      data-shape={health}
    >
      <Shape health={health} />
    </svg>
  );
}

/** The mark of the menu bar: nothing before any answer has come, as when signed out. */
export function HealthMark() {
  const said = useSyncExternalStore(serverHealth.subscribe, serverHealth.get);
  if (!said) return null;
  const words = healthWords(said);
  return (
    <Link
      className="health-mark"
      to="/about"
      title={healthTitle(said)}
      aria-label={`Server health: ${words}`}
      data-testid="health-mark"
      data-health={said.health}
      data-refusing={said.refusing}
    >
      <HealthShape health={said.health} />
    </Link>
  );
}
