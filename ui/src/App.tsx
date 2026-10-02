import { ErrorBoundary } from "@/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "@/features/errors/ErrorDialog";

export function App() {
  return (
    <div className="min-h-dvh font-sans">
      <header className="mx-auto flex max-w-2xl items-center px-8 pt-8">
        <h1 className="text-2xl font-semibold">dsj</h1>
      </header>
      <main className="mx-auto max-w-2xl px-8 py-4">
        <ErrorBoundary>
          <p className="text-muted-foreground">The library is empty.</p>
        </ErrorBoundary>
      </main>
      <ShownErrorDialog />
    </div>
  );
}
