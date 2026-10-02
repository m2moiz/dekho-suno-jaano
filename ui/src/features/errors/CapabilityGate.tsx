import type { ReactNode } from "react";

import { capabilityError } from "./capability";
import { ErrorDialog } from "./ErrorDialog";

/**
 * The app, or the #82 dialog naming what this browser lacks (#107).
 *
 * Checked during the first render, which runs before the first paint, so a
 * browser that cannot run the reader never shows it, not even for a frame.
 */
export function CapabilityGate({
  children,
  win = window,
}: {
  children: ReactNode;
  win?: Parameters<typeof capabilityError>[0];
}) {
  const lacking = capabilityError(win);
  if (lacking !== null) return <ErrorDialog error={lacking} />;
  return children;
}
