// Everything FCC Phone keeps lives in the phone's IndexedDB. If the browser
// refuses storage (private mode), it still works for this visit, in memory.

const memoryOnly = new Map();
let opening = null;

function open() {
  if (!("indexedDB" in window)) return Promise.resolve(null);
  opening =
    opening ||
    new Promise((resolve) => {
      try {
        const request = indexedDB.open("fcc-phone", 1);
        request.onupgradeneeded = () => request.result.createObjectStore("kv");
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => resolve(null);
      } catch {
        resolve(null);
      }
    });
  return opening;
}

async function run(mode, work) {
  const db = await open();
  if (!db) return work(null);
  return new Promise((resolve, reject) => {
    const tx = db.transaction("kv", mode);
    const request = work(tx.objectStore("kv"));
    tx.oncomplete = () => resolve(request ? request.result : undefined);
    tx.onerror = () => reject(tx.error);
  });
}

export const store = {
  async get(key, fallback) {
    try {
      const value = await run("readonly", (kv) => (kv ? kv.get(key) : null));
      if (value !== undefined && value !== null) return value;
    } catch {
      /* fall back to the copy in memory */
    }
    return memoryOnly.has(key) ? memoryOnly.get(key) : fallback;
  },
  async set(key, value) {
    memoryOnly.set(key, value);
    try {
      await run("readwrite", (kv) => (kv ? kv.put(value, key) : null));
    } catch {
      /* kept in memory for this visit */
    }
  },
  async remove(key) {
    memoryOnly.delete(key);
    try {
      await run("readwrite", (kv) => (kv ? kv.delete(key) : null));
    } catch {
      /* nothing to remove */
    }
  },
  durable: async () => Boolean(await open()),
};
