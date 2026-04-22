import { writable } from 'svelte/store';

export interface LibraryRun {
  run_id: string;
  description: string;
  created_at: string;
  session_ids: string[];
  sha_set: string[];
}

const STORAGE_KEY = 'bodaqs_library';

function load(): LibraryRun[] {
  if (typeof localStorage === 'undefined') return [];
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? '[]') as LibraryRun[];
  } catch {
    return [];
  }
}

function save(runs: LibraryRun[]): void {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(runs));
  }
}

function createLibraryStore() {
  const { subscribe, update } = writable<LibraryRun[]>(load());

  return {
    subscribe,
    addSessionToRun(runId: string, sessionId: string, sha256: string): void {
      update((runs) => {
        const existing = runs.find((r) => r.run_id === runId);
        if (existing) {
          if (sessionId && !existing.session_ids.includes(sessionId)) {
            existing.session_ids.push(sessionId);
          }
          if (sha256 && !existing.sha_set.includes(sha256)) {
            existing.sha_set.push(sha256);
          }
        } else {
          runs.push({
            run_id: runId,
            description: '',
            created_at: new Date().toISOString(),
            session_ids: sessionId ? [sessionId] : [],
            sha_set: sha256 ? [sha256] : [],
          });
        }
        save(runs);
        return [...runs];
      });
    },
    hasSha(sha256: string): boolean {
      let found = false;
      const unsub = subscribe((runs) => {
        found = runs.some((r) => r.sha_set.includes(sha256));
      });
      unsub();
      return found;
    },
    setDescription(runId: string, description: string): void {
      update((runs) => {
        const run = runs.find((r) => r.run_id === runId);
        if (run) run.description = description;
        save(runs);
        return [...runs];
      });
    },
  };
}

export const libraryStore = createLibraryStore();
