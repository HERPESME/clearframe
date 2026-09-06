import type {
  Action,
  LicenceGrant,
  ProductionState,
  ProductionSummary,
  Role,
} from "./types";

let currentRole: Role = "legal";

export function setRole(role: Role) {
  currentRole = role;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-ClearFrame-Role": currentRole,
      ...(init?.headers ?? {}),
    },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body?.detail);
  }
  return resp.json() as Promise<T>;
}

export class ApiError extends Error {
  status: number;
  detail: unknown;
  constructor(status: number, detail: unknown) {
    super(`API error ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

// FormData must NOT get an explicit Content-Type: the browser has to set the
// multipart boundary itself.
async function upload<T>(path: string, form: FormData): Promise<T> {
  const resp = await fetch(path, {
    method: "POST",
    body: form,
    headers: { "X-ClearFrame-Role": currentRole },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body?.detail);
  }
  return resp.json() as Promise<T>;
}

export const api = {
  meta: () =>
    request<{
      mode: "demo" | "live";
      version: string;
      auth: boolean;
      open_roles: boolean;
      user: { uid: string; email: string | null; name: string | null; role: string } | null;
    }>("/api/meta"),
  listProductions: () => request<ProductionSummary[]>("/api/productions"),
  createDemo: () => request<ProductionState>("/api/productions/demo", { method: "POST" }),
  startPacedDemo: (paceS: number) =>
    request<{ status: string }>("/api/productions/demo", {
      method: "POST",
      body: JSON.stringify({ pace_s: paceS }),
    }),
  eventsUrl: (pid: string) => `/api/productions/${pid}/events`,
  getProduction: (id: string) => request<ProductionState>(`/api/productions/${id}`),
  recordDecision: (pid: string, elementId: string, action: Action, note: string) =>
    request<{ ok: boolean; pending: string[] }>(`/api/productions/${pid}/decisions`, {
      method: "POST",
      body: JSON.stringify({ element_id: elementId, action, note }),
    }),
  uploadFootage: (
    file: File,
    opts: {
      title: string;
      territories: string;
      distribution: string;
      use_context: string;
      sponsors: string;
      platform: string;
    },
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", opts.title);
    // No `production_id`. It used to be the literal "upload" from here, meeting
    // the same default on the server, so every user's footage landed in one
    // slot — the same state file and media directory, with each upload deleting
    // the last one's cached boxes and thumbnails. The server issues an id now
    // and returns it; this call already reads it back from the response.
    form.append("territories", opts.territories);
    form.append("distribution", opts.distribution);
    form.append("use_context", opts.use_context);
    form.append("sponsors", opts.sponsors);
    form.append("platform", opts.platform);
    return upload<{ production_id: string; status: string }>("/api/productions", form);
  },
  uploadLicences: (file: File, replace: boolean) => {
    const form = new FormData();
    form.append("file", file);
    form.append("replace", String(replace));
    return upload<{ stored: number; added: number }>("/api/licences", form);
  },
  listLicences: () => request<{ licences: LicenceGrant[] }>("/api/licences"),
  mediaUrl: (pid: string) => `/api/productions/${pid}/media`,
  checkFreshness: (pid: string) =>
    request<{ checked: number; holders: number; material_signals: number }>(
      `/api/productions/${pid}/freshness`,
      { method: "POST" },
    ),
  generateDossier: (pid: string) =>
    request<{ artifacts: string[] }>(`/api/productions/${pid}/dossier`, {
      method: "POST",
    }),
  artifactUrl: (pid: string, name: string) => `/api/productions/${pid}/artifacts/${name}`,
};
