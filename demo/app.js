import { SOURCES, selectOutput, verifyData, viewLabel } from './schema.mjs';
import { readExampleData } from './transport.mjs';

const byId = id => document.getElementById(id);
const descriptions = {
  learned: 'Learned ordering of the full-hybrid pool. Scores are not probabilities.',
  rrf: 'Reciprocal rank fusion before learned ranking. The candidate pool is unchanged.',
  recent: 'Recent popularity for a first visit. No user-history personalization.',
};
const labels = { learned: 'Learned ranking', rrf: 'Retrieval order (RRF)', recent: 'Recent popularity' };
const element = (tag, text, className) => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
};
let data;

function render() {
  const profile = data.profiles.find(profile => profile.id === byId('profile').value);
  const order = byId('ordering').value;
  const output = selectOutput(profile, order, Number(byId('limit').value));
  byId('profile-summary').textContent = profile.cohort === 'warm'
    ? 'A returning user from the sealed reference sample. The alias hides the original user ID.'
    : 'An explicit empty-history context. Every first visit uses this same cold route.';
  byId('history-count').textContent = profile.history_items.toLocaleString('en-US');
  byId('pool-count').textContent = profile.candidate_count.toLocaleString('en-US');
  byId('order-description').textContent = descriptions[order];
  byId('route').textContent = viewLabel(profile, order);
  byId('results-title').textContent = `${labels[order]} · Top ${output.length}`;
  byId('result-status').textContent = `${profile.label}, ${labels[order]}, ${output.length} products shown.`;
  const fragment = document.createDocumentFragment();
  output.forEach((item, index) => {
    const row = element('li', '');
    const details = element('details', '');
    const summary = element('summary', '');
    const expand = element('span', '+', 'expand');
    expand.setAttribute('aria-hidden', 'true');
    summary.append(element('span', String(index + 1).padStart(2, '0'), 'rank'),
      element('span', `Item ${item.item_id}`, 'item-title'),
      element('span', item.category_id === null ? 'Category unknown' : `Category ${item.category_id}`, 'category'), expand);
    const evidence = element('div', '', 'evidence');
    evidence.append(element('p', `Position in the retrieval pool: ${item.retrieval_rank}. Source-list ranks:`));
    const list = element('ul', '');
    item.sources.forEach(source => list.append(element('li', `${SOURCES[source.source]} · rank ${source.rank}`)));
    evidence.append(list);
    details.append(summary, evidence);
    row.append(details); fragment.append(row);
  });
  byId('products').replaceChildren(fragment);
}

function changeProfile() {
  const profile = data.profiles.find(profile => profile.id === byId('profile').value);
  const previousOrder = byId('ordering').value;
  byId('ordering').replaceChildren(...Object.keys(profile.orders).map(order => new Option(labels[order], order)));
  if (Object.hasOwn(profile.orders, previousOrder)) byId('ordering').value = previousOrder;
  render();
}

async function start() {
  try {
    data = await verifyData(await readExampleData(), crypto.subtle);
    byId('profile').replaceChildren(...data.profiles.map(profile => new Option(profile.label, profile.id)));
    byId('model-version').textContent = data.model.version;
    byId('cutoff').textContent = new Date(data.model.cutoff_ms).toISOString();
    byId('snapshot-date').textContent = `Fold ${data.model.fold} · ${new Date(data.model.cutoff_ms).toISOString().slice(0, 10)}`;
    byId('manifest').textContent = data.model.manifest_sha256;
    changeProfile();
    byId('profile').addEventListener('change', changeProfile);
    byId('ordering').addEventListener('change', render);
    byId('limit').addEventListener('change', render);
    byId('workspace').hidden = false;
    byId('load-status').hidden = true;
  } catch {
    byId('workspace').hidden = true;
    byId('load-status').textContent = 'Example data could not be verified. Reload to retry. The methodology below remains available; no substitute recommendations are shown.';
  }
}
start();
