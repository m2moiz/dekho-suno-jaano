import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { startHeartbeat, takeToken } from "@/features/session/session";
import "@/index.css";

// Before anything renders, so the token is off the address bar at once (#112).
const token = takeToken();
if (token !== null) {
  startHeartbeat();
}

const root = document.getElementById("root");
if (root === null) {
  throw new Error("index.html has no #root element to mount the app into");
}
createRoot(root).render(
  <StrictMode>
    <App hasToken={token !== null} />
  </StrictMode>,
);
