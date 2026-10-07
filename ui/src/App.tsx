import { ErrorBoundary } from "@/features/errors/ErrorBoundary";
import { ShownErrorDialog } from "@/features/errors/ErrorDialog";
import { LibraryPage } from "@/features/library/LibraryPage";
import { ReviewPage } from "@/features/review/ReviewPage";
import { KeySheet } from "@/features/shell/KeySheet";
import { TranscriptPage } from "@/features/transcript/TranscriptPage";
import { readRoute } from "@/lib/route";

/**
 * Each page draws its own bar (AppBar), because what the bar carries is the
 * page's: search and Add recording on the library, the title and the
 * transcript's tools on a transcript, progress and the pass in Review.
 */
export function App() {
  const route = readRoute(window.location.search);
  return (
    <div className="flex min-h-dvh flex-col font-sans">
      <ErrorBoundary>
        {route.page === "transcript" ? (
          <TranscriptPage recording={route.recording} transcript={route.transcript} />
        ) : route.page === "review" ? (
          <ReviewPage recording={route.recording} transcript={route.transcript} />
        ) : (
          <LibraryPage />
        )}
      </ErrorBoundary>
      <ShownErrorDialog />
      <KeySheet />
    </div>
  );
}
