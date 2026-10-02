import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { fromThrown, showError } from "@/features/errors/appError";
import { CapabilityGate } from "@/features/errors/CapabilityGate";
import { NO_TOKEN, startHeartbeat, takeToken } from "@/features/session/session";
import "@/index.css";

// Anything thrown outside a render, in a handler or a promise nobody awaited,
// still reaches the error dialog with its own words (#82).
window.addEventListener("error", (event) => showError(fromThrown(event.error ?? event.message)));
window.addEventListener("unhandledrejection", (event) => showError(fromThrown(event.reason)));

// Before anything renders, so the token is off the address bar at once (#112).
const token = takeToken();
if (token === null) {
  showError(NO_TOKEN);
} else {
  startHeartbeat();
}

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element to mount the app into");
}
createRoot(root).render(
  <StrictMode>
    <CapabilityGate>
      <App />
    </CapabilityGate>
  </StrictMode>,
);
