import type { Action, ProductionState, Role } from "./types";

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

export const api = {
  listProductions: () =>
    request<{ id: string; title: string; stage_status: Record<string, string> }[]>(
      "/api/productions",
    ),
  createDemo: () => request<ProductionState>("/api/productions/demo", { method: "POST" }),
  getProduction: (id: string) => request<ProductionState>(`/api/productions/${id}`),
  recordDecision: (pid: string, elementId: string, action: Action, note: string) =>
    request<{ ok: boolean; pending: string[] }>(`/api/productions/${pid}/decisions`, {
      method: "POST",
      body: JSON.stringify({ element_id: elementId, action, note }),
    }),
  generateDossier: (pid: string) =>
    request<{ artifacts: string[] }>(`/api/productions/${pid}/dossier`, {
      method: "POST",
    }),
  artifactUrl: (pid: string, name: string) => `/api/productions/${pid}/artifacts/${name}`,
};
