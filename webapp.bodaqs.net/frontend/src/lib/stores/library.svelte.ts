import { getAllRuns, saveRun } from "$lib/db/artifacts";
import type { Run } from "$lib/db/dexie";

function createLibraryStore() {
  let runs = $state<Run[]>([]);
  let loading = $state(false);

  async function load(): Promise<void> {
    loading = true;
    try {
      runs = await getAllRuns();
    } finally {
      loading = false;
    }
  }

  async function addRun(run: Run): Promise<void> {
    await saveRun(run);
    runs = await getAllRuns();
  }

  return {
    get runs() {
      return runs;
    },
    get loading() {
      return loading;
    },
    load,
    addRun
  };
}

export const libraryStore = createLibraryStore();
