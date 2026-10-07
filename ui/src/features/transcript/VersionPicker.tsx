import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { versionLabel } from "@/features/library/describe";
import { FIELD_BUTTON, FIELD_EDGE } from "@/features/shell/field";
import type { RecordingRow } from "@/features/library/types";
import { transcriptHref } from "@/lib/route";

/** The recording's other transcripts, when it has more than one (Hashiya spec, Reader: "version picker"). */
export function VersionPicker({ recording, transcript }: { recording: RecordingRow; transcript: number }) {
  if (recording.transcripts.length < 2) return null;
  const items = recording.transcripts.map((t) => ({ value: t.id, label: versionLabel(t) }));
  return (
    <Select
      items={items}
      value={transcript}
      onValueChange={(picked) => {
        if (typeof picked === "number" && picked !== transcript) window.location.assign(transcriptHref(recording.id, picked));
      }}
    >
      <SelectTrigger aria-label="Version" className={`h-11 max-w-60 dark:bg-transparent ${FIELD_EDGE} ${FIELD_BUTTON}`}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {items.map((item) => (
          <SelectItem key={item.value} value={item.value}>
            {item.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
