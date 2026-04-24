import { removePreprocessResult } from "$lib/db/artifacts";

export interface LibraryRun {
  run_id: string;
  description: string;
  created_at: string;
  session_ids: string[];
  sha_set: string[];
}

const STORAGE_KEY = "bodaqs_library";

function load(): LibraryRun[] {
  if (typeof localStorage === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]") as LibraryRun[];
  } catch {
    return [];
  }
}

function save(runs: LibraryRun[]): void {
  if (typeof localStorage !== "undefined") {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
  }
}

class LibraryStore {
  #runs = $state<LibraryRun[]>(load());

  get runs() {
    return this.#runs;
  }

  addSessionToRun(runId: string, sessionId: string, sha256: string): void {
    const existing = this.#runs.find((r) => r.run_id === runId);
    if (existing) {
      if (sessionId && !existing.session_ids.includes(sessionId)) {
        existing.session_ids.push(sessionId);
      }
      if (sha256 && !existing.sha_set.includes(sha256)) {
        existing.sha_set.push(sha256);
      }
    } else {
      this.#runs.push({
        run_id: runId,
        description: "",
        created_at: new Date().toISOString(),
        session_ids: sessionId ? [sessionId] : [],
        sha_set: sha256 ? [sha256] : []
      });
    }
    save(this.#runs);
  }

  hasSha(sha256: string): boolean {
    return this.#runs.some((r) => r.sha_set.includes(sha256));
  }

  setDescription(runId: string, description: string): void {
    const run = this.#runs.find((r) => r.run_id === runId);
    if (run) run.description = description;
    save(this.#runs);
  }

  async clear() {
    for (const run of this.#runs) {
      await removePreprocessResult(run.run_id);
    }

    try {
      localStorage.removeItem(STORAGE_KEY);
      this.#runs = [];
    } catch (e) {
      console.error(e);
    }
  }
}

export const libraryStore = new LibraryStore();
