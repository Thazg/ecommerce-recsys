import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { webcrypto } from 'node:crypto';
import { canonical, selectOutput, validateData, verifyData, viewLabel } from '../../demo/schema.mjs';
import { readExampleData } from '../../demo/transport.mjs';

const original = JSON.parse(await readFile(new URL('../../demo/data/showcase_v1.json', import.meta.url), 'utf8'));
const clone = () => structuredClone(original);

test('published real export satisfies strict contract and canonical content checksum', async () => {
  assert.equal(await verifyData(clone(), webcrypto.subtle) instanceof Object, true);
});

test('every profile/order preserves Top-5/10 prefixes of Top-20', () => {
  for (const profile of original.profiles) {
    for (const order of Object.keys(profile.orders)) {
      const all = selectOutput(profile, order, 20);
      assert.deepEqual(selectOutput(profile, order, 5), all.slice(0, 5));
      assert.deepEqual(selectOutput(profile, order, 10), all.slice(0, 10));
      assert.equal(all.length, 20);
    }
  }
});

test('cold has only recent ordering; invalid K cannot silently coerce', () => {
  const cold = original.profiles.at(-1);
  assert.throws(() => selectOutput(cold, 'learned', 20));
  for (const k of [0, 1, 1000, true, '20', NaN]) {
    assert.throws(() => selectOutput(cold, 'recent', k));
  }
});

test('reject private fields at every public object boundary', () => {
  for (const insert of [d => d, d => d.model, d => d.provenance,
    d => d.profiles[0], d => d.profiles[0].items[0], d => d.profiles[0].items[0].sources[0]]) {
    const data = clone(); insert(data).user_id = 'private';
    assert.throws(() => validateData(data));
  }
});

test('mismatched content hash fails even when schema remains valid', async () => {
  const data = clone(); data.profiles[0].history_items += 1;
  await assert.rejects(verifyData(data, webcrypto.subtle));
});

test('canonical serialization sorts object keys but preserves ranking arrays', () => {
  assert.equal(canonical({ z: [2, 1], a: false }), '{"a":false,"z":[2,1]}');
});

test('duplicates, foreign items, invalid ranks, routes and markup are rejected', () => {
  const faults = [
    d => { d.profiles[0].orders.learned[1] = d.profiles[0].orders.learned[0]; },
    d => { d.profiles[0].orders.learned[0] = '9999999999999999'; },
    d => { d.profiles[0].items[0].sources[0].rank = true; },
    d => { d.profiles[0].items[0].sources[0].source = 'toString'; },
    d => { d.profiles[0].items[0].category_id = '<script>'; },
    d => { d.profiles[0].route = 'recent_popularity'; },
    d => { d.model.manifest_sha256 = '0'.repeat(64); },
    d => { d.provenance.live_inference = true; },
    d => { d.profiles.reverse(); },
  ];
  for (const fault of faults) { const data = clone(); fault(data); assert.throws(() => validateData(data)); }
});

test('warm RRF is the original pool prefix; learned order only reorders that pool', () => {
  for (const profile of original.profiles.slice(0, 4)) {
    const rrf = selectOutput(profile, 'rrf', 20);
    assert.deepEqual(rrf.map(item => item.retrieval_rank), Array.from({ length: 20 }, (_, i) => i + 1));
    assert.ok(selectOutput(profile, 'learned', 20).every(item => item.retrieval_rank <= profile.candidate_count));
  }
});

test('comparison view is distinguished from the locked warm/cold routes', () => {
  assert.equal(viewLabel(original.profiles[0], 'rrf'), 'Comparison ordering');
  assert.equal(viewLabel(original.profiles[0], 'learned'), 'Locked warm route');
  assert.equal(viewLabel(original.profiles.at(-1), 'recent'), 'Locked cold route');
  assert.throws(() => viewLabel(original.profiles.at(-1), 'rrf'));
});

test('bounded transport reads valid UTF-8 JSON with anonymous fixed URL', async () => {
  const data = await readExampleData({ fetchImpl: async (url, options) => {
    assert.equal(url, './data/showcase_v1.json');
    assert.equal(options.credentials, 'omit');
    assert.ok(options.signal instanceof AbortSignal);
    return new Response(JSON.stringify({ message: 'café' }));
  }});
  assert.deepEqual(data, { message: 'café' });
});

test('oversized Content-Length is rejected before a body reader is acquired', async () => {
  await assert.rejects(readExampleData({ fetchImpl: async () => ({
    ok: true, headers: new Headers({ 'content-length': '256001' }),
    body: { getReader() { assert.fail('must refuse before reading'); } },
  }) }), /byte budget/);
});

test('actual bytes are bounded for absent and understated Content-Length', async () => {
  for (const headers of [{}, { 'content-length': '1' }]) {
    let cancelled = false;
    const body = new ReadableStream({
      start(controller) { controller.enqueue(new Uint8Array(4)); controller.enqueue(new Uint8Array(4)); },
      cancel() { cancelled = true; },
    });
    await assert.rejects(readExampleData({ maxBytes: 7,
      fetchImpl: async () => new Response(body, { headers }),
    }), /byte budget/);
    assert.equal(cancelled, true);
  }
});

test('one absolute deadline covers stalled headers and stalled body; abort/cancel is owned', async () => {
  let headerSignal;
  await assert.rejects(readExampleData({ timeoutMs: 25, fetchImpl: (_, { signal }) => {
    headerSignal = signal; return new Promise(() => {});
  }}), /timed out/);
  assert.equal(headerSignal.aborted, true);
  let bodyCancelled = false;
  const stream = new ReadableStream({ cancel() { bodyCancelled = true; return new Promise(() => {}); } });
  await assert.rejects(readExampleData({ timeoutMs: 25,
    fetchImpl: async () => new Response(stream),
  }), /timed out/);
  assert.equal(bodyCancelled, true);
});

test('HTTP error, malformed JSON and invalid UTF-8 fail closed', async () => {
  for (const response of [new Response('missing', { status: 404 }),
    new Response('{'), new Response(new Uint8Array([0xff]))]) {
    await assert.rejects(readExampleData({ fetchImpl: async () => response }));
  }
});

test('multibyte content uses byte count, not decoded character count', async () => {
  await assert.rejects(readExampleData({ maxBytes: 4,
    fetchImpl: async () => new Response('"éé"'),
  }), /byte budget/);
});
