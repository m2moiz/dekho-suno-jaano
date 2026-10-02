// The reply of GET /api/recordings, as dsj/ui/schemas.py defines it, through
// the types `just api` generates (#155): a field renamed in Python and not
// here is a tsc error.

import type { components } from "@/api/schema";

export type RecordingRow = components["schemas"]["Recording"];
export type TranscriptRow = components["schemas"]["Transcript"];
