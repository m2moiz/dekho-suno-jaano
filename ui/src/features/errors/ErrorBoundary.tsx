import { Component, type ErrorInfo, type ReactNode } from "react";

import { type AppError, fromThrown } from "./appError";
import { ErrorDialog } from "./ErrorDialog";

type State = { error: AppError | null };

/**
 * A crash inside a view shows the error dialog with a reload button, instead
 * of React tearing the whole window down to white (#82). Placed around the
 * view, not the app, so the window's frame stays up.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(thrown: unknown): State {
    return { error: fromThrown(thrown) };
  }

  override componentDidCatch(thrown: unknown, info: ErrorInfo): void {
    // The dialog shows the message; the component stack is for whoever debugs it.
    console.error("dsj ui: a view crashed", thrown, info.componentStack);
  }

  override render(): ReactNode {
    if (this.state.error === null) return this.props.children;
    return (
      <>
        <p className="text-muted-foreground">This view stopped. Reload to try again.</p>
        <ErrorDialog error={this.state.error} onReload={() => window.location.reload()} />
      </>
    );
  }
}
