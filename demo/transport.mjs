// Bound the entire download, including response headers and a stalled body.
export const DATA_URL = './data/showcase_v1.json';

export async function readExampleData({ fetchImpl = fetch, timeoutMs = 10000, maxBytes = 256000 } = {}) {
  if (!Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 60000 ||
      !Number.isSafeInteger(maxBytes) || maxBytes < 1 || maxBytes > 256000) {
    throw new Error('Invalid download limits');
  }
  const controller = new AbortController();
  let reader;
  let completed = false;
  let timer;
  const deadline = new Promise((_, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new Error('Example download timed out'));
    }, timeoutMs);
  });
  const bounded = promise => Promise.race([promise, deadline]);
  try {
    const response = await bounded(fetchImpl(DATA_URL, {
      credentials: 'omit', cache: 'no-cache', signal: controller.signal,
    }));
    if (!response.ok || !response.body) throw new Error('Example data unavailable');
    const declared = response.headers.get('content-length');
    if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > maxBytes)) {
      throw new Error('Example data exceeds byte budget');
    }
    reader = response.body.getReader();
    const chunks = [];
    let size = 0;
    while (true) {
      const { done, value } = await bounded(reader.read());
      if (done) break;
      if (!(value instanceof Uint8Array) || value.byteLength > maxBytes - size) {
        throw new Error('Example data exceeds byte budget');
      }
      chunks.push(value);
      size += value.byteLength;
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    const data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    completed = true;
    return data;
  } finally {
    clearTimeout(timer);
    if (!completed) {
      controller.abort();
      // Cancellation itself may stall in a faulty transport; never wait for it.
      if (reader) Promise.resolve(reader.cancel()).catch(() => {});
    }
  }
}
