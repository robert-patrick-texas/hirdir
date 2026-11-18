import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { FaultBoundary } from "./components/Fault";
import { slashed } from "./lib/base";
import "./styles.css";

// Opened at the prefix without its final slash: show the address the router knows.
const better = slashed(document.baseURI, window.location.pathname);
if (better !== null) {
  window.history.replaceState(
    window.history.state,
    "",
    better + window.location.search + window.location.hash,
  );
}

const root = document.getElementById("root");
if (!root) throw new Error("the page has no #root element");
// 0.9.7: a fault in the frame itself, the menu bar or what is around it, says so too,
// over the whole page (P-230). What the page held before its script ran is replaced.
createRoot(root).render(
  <StrictMode>
    <FaultBoundary whole>
      <App />
    </FaultBoundary>
  </StrictMode>,
);
