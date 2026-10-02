import { ErrorBoundary } from "@/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "@/features/errors/ErrorDialog";
import { LibraryPage } from "@/features/library/LibraryPage";
import { ThemeControl } from "@/features/theme/ThemeControl";
import { TranscriptPage } from "@/features/transcript/TranscriptPage";
import { readRoute } from "@/lib/route";

export function App() {
  const route = readRoute(window.location.search);
  // The transcript's own 68ch measure is set in its larger type, so its page
  // is wider than the library's list.
  const width = route.page === "transcript" ? "max-w-3xl" : "max-w-2xl";
  return (
    <div className="min-h-dvh font-sans">
      <header className={`mx-auto flex ${width} items-center justify-between gap-4 px-8 pt-8`}>
        <h1 className="text-2xl font-semibold">
          <a href="/">dsj</a>
        </h1>
        <ThemeControl />
      </header>
      <main className={`mx-auto ${width} px-8 py-4`}>
        <ErrorBoundary>
          {route.page === "transcript" ? (
            <TranscriptPage recording={route.recording} transcript={route.transcript} />
          ) : (
            <LibraryPage />
          )}
        </ErrorBoundary>
      </main>
      <ShownErrorDialog />
    </div>
  );
}
