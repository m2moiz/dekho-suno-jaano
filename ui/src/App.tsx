import { ErrorBoundary } from "@/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "@/features/errors/ErrorDialog";
import { LibraryPage } from "@/features/library/LibraryPage";
import { ThemeControl } from "@/features/theme/ThemeControl";

export function App() {
  return (
    <div className="min-h-dvh font-sans">
      <header className="mx-auto flex max-w-2xl items-center justify-between gap-4 px-8 pt-8">
        <h1 className="text-2xl font-semibold">dsj</h1>
        <ThemeControl />
      </header>
      <main className="mx-auto max-w-2xl px-8 py-4">
        <ErrorBoundary>
          <LibraryPage />
        </ErrorBoundary>
      </main>
      <ShownErrorDialog />
    </div>
  );
}
