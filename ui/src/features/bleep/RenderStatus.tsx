import { Progress } from "@/components/ui/progress";
import { fileName } from "@/features/library/describe";
import { isOver, type RenderJob, renderSrc } from "./render";

/** Where a render from the page is, and when it is done, where its file is and a way to hear it. */
export function RenderStatus({ job }: { job: RenderJob }) {
  if (!isOver(job)) {
    return (
      <div className="flex flex-col gap-1" role="status" aria-label="Rendering">
        <span className="text-muted-foreground">
          Rendering {fileName(job.output)}: {Math.round(job.fraction * 100)}%
        </span>
        <Progress value={Math.round(job.fraction * 100)} />
      </div>
    );
  }
  if (job.state === "failed") {
    return (
      <p className="text-destructive select-text" role="status">
        The render failed: {job.error}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-1" role="status" aria-label="Rendered">
      <span>
        Rendered {job.spans === 1 ? "1 span" : `${job.spans} spans`} into{" "}
        <a href={renderSrc(job.id)} target="_blank" rel="noreferrer" className="underline underline-offset-4">
          {fileName(job.output)}
        </a>
        , beside the recording, with its log and its source note.
      </span>
      <span className="font-mono text-xs break-all text-muted-foreground">{job.output}</span>
      {/* Hear it here, against the preview, without leaving the page. */}
      <audio src={renderSrc(job.id)} controls preload="none" className="h-10 w-full" aria-label="Rendered file" />
      {job.notes.map((note) => (
        <span key={note} className="text-xs text-muted-foreground">
          {note}
        </span>
      ))}
    </div>
  );
}
