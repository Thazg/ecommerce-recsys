// Static data contract: no private user mappings or arbitrary runtime inputs.
export const MANIFEST = '84ddc7b2e34b92728164f60346e2115cdcc07415af72aed60859c78ffbb5aabe';
export const SOURCES = {
  item_knn: 'ItemKNN', als: 'ALS', category_popularity: 'Category popularity',
  recent_popularity: 'Recent popularity', global_popularity: 'Global popularity',
};

function assert(condition) {
  if (!condition) throw new Error('Example data does not match the published contract.');
}
function keys(value, expected) {
  assert(value !== null && typeof value === 'object' && !Array.isArray(value));
  assert(Object.keys(value).sort().join('|') === [...expected].sort().join('|'));
}
const code = value => typeof value === 'string' && /^\d{1,16}$/.test(value);
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
const integer = (n, min, max) => Number.isSafeInteger(n) && n >= min && n <= max;

export function validateData(data) {
  keys(data, ['schema_version', 'mode', 'model', 'provenance', 'profiles', 'content_sha256']);
  assert(data.schema_version === 1 && data.mode === 'precomputed_model_outputs');
  keys(data.model, ['version', 'manifest_sha256', 'cutoff_ms', 'fold']);
  assert(data.model.manifest_sha256 === MANIFEST);
  assert(data.model.version === 'retailrocket-fold09-v1' && data.model.fold === 9);
  assert(data.model.cutoff_ms === 1441216678608 && hash(data.content_sha256));
  keys(data.provenance, ['exporter_sha256_lf', 'inference_code_sha256', 'sealed_references_sha256',
    'selection', 'reference_trace_parity', 'examples', 'quality_recomputed', 'live_inference']);
  for (const name of ['exporter_sha256_lf', 'inference_code_sha256', 'sealed_references_sha256']) {
    assert(hash(data.provenance[name]));
  }
  assert(data.provenance.selection === 'fixed reference positions 0,25,50,75 plus cold; no target inspection');
  assert(data.provenance.reference_trace_parity === true && data.provenance.examples === 5);
  assert(data.provenance.quality_recomputed === false && data.provenance.live_inference === false);
  assert(Array.isArray(data.profiles) && data.profiles.length === 5);
  data.profiles.forEach((profile, i) => {
    keys(profile, ['id', 'label', 'cohort', 'route', 'history_items', 'candidate_count', 'orders', 'items']);
    const warm = i < 4;
    assert(profile.id === (warm ? `profile-0${i + 1}` : 'cold-start'));
    assert(profile.label === (warm ? `Snapshot profile 0${i + 1}` : 'First visit'));
    assert(profile.cohort === (warm ? 'warm' : 'cold'));
    assert(profile.route === (warm ? 'hybrid_learned' : 'recent_popularity'));
    assert(integer(profile.history_items, warm ? 1 : 0, warm ? 224190 : 0));
    assert(integer(profile.candidate_count, 1, 1000));
    keys(profile.orders, warm ? ['learned', 'rrf'] : ['recent']);
    assert(Array.isArray(profile.items) && profile.items.length <= 40);
    const ids = new Set();
    const ranks = new Set();
    profile.items.forEach(item => {
      keys(item, ['item_id', 'category_id', 'retrieval_rank', 'sources']);
      assert(code(item.item_id) && (item.category_id === null || code(item.category_id)));
      assert(!ids.has(item.item_id) && !ranks.has(item.retrieval_rank));
      ids.add(item.item_id); ranks.add(item.retrieval_rank);
      assert(integer(item.retrieval_rank, 1, profile.candidate_count));
      assert(Array.isArray(item.sources) && item.sources.length >= 1 && item.sources.length <= 5);
      const names = new Set();
      item.sources.forEach(source => {
        keys(source, ['source', 'rank']);
        assert(Object.hasOwn(SOURCES, source.source) && !names.has(source.source));
        names.add(source.source);
        assert(integer(source.rank, 1, 1000));
      });
      if (!warm) assert(item.sources.length === 1 && item.sources[0].source === 'recent_popularity');
    });
    const used = new Set();
    Object.values(profile.orders).forEach(order => {
      assert(Array.isArray(order) && order.length === Math.min(20, profile.candidate_count));
      assert(new Set(order).size === order.length && order.every(id => ids.has(id)));
      order.forEach(id => used.add(id));
    });
    assert(used.size === ids.size);
    const retrievalOrder = profile.orders[warm ? 'rrf' : 'recent'];
    retrievalOrder.forEach((id, rank) => {
      assert(profile.items.find(item => item.item_id === id).retrieval_rank === rank + 1);
    });
  });
  return data;
}

export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value !== null && typeof value === 'object') {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

export async function verifyData(data, subtle) {
  validateData(data);
  const { content_sha256, ...payload } = data;
  const result = await subtle.digest('SHA-256', new TextEncoder().encode(canonical(payload)));
  const actual = [...new Uint8Array(result)].map(byte => byte.toString(16).padStart(2, '0')).join('');
  assert(actual === content_sha256);
  return data;
}

export function selectOutput(profile, ordering, limit) {
  assert(Object.hasOwn(profile.orders, ordering) && [5, 10, 20].includes(limit));
  return profile.orders[ordering].slice(0, limit).map(id => profile.items.find(item => item.item_id === id));
}

export function viewLabel(profile, ordering) {
  assert(Object.hasOwn(profile.orders, ordering));
  return ordering === 'rrf' ? 'Comparison ordering' :
    profile.cohort === 'warm' ? 'Locked warm route' : 'Locked cold route';
}
