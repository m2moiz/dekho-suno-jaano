// The page's one way to call the dsj ui server. Paths, parameters and replies
// are typed from schema.d.ts, which `just api` generates from dsj/ui/schemas.py,
// so a route or field that Python no longer has is a tsc error here (#155).
import createClient from "openapi-fetch";

import type { paths } from "@/api/schema";

// Same origin: dsj ui serves this page and its API from one loopback port, and
// `just ui-dev` proxies /api to the Python side so dev matches. Spelled out
// rather than "": a browser resolves a relative Request against the page, but
// the unit tests' fetch does not, and the two must build the same URL.
export const api = createClient<paths>({ baseUrl: window.location.origin });
