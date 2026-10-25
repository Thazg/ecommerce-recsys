// An illustrative content-based policy. No Retailrocket weights or user IDs.
export const SCHEMA = "recolens-shopping-v1";
const RATINGS = new Map([[1, -6], [2, -3], [3, 0], [4, 3], [5, 6]]);
const FAMILIES = { tech: "digital", accessories: "digital", men: "fashion", women: "fashion", style: "fashion", home: "living", kitchen: "living", care: "care", sport: "sport", food: "food" };

export function validateCatalog(value) {
  if (value?.schema !== SCHEMA || value.currency !== "USD" ||
      !Array.isArray(value.groups) || value.groups.length !== 10 ||
      !Array.isArray(value.products) || value.products.length !== 100) {
    throw new Error("Invalid sample catalog.");
  }
  const groups = new Set();
  for (const group of value.groups) {
    if (!group || typeof group.id !== "string" || !Object.hasOwn(FAMILIES, group.id) ||
        typeof group.label !== "string" || !group.label || groups.has(group.id)) {
      throw new Error("Invalid product group.");
    }
    groups.add(group.id);
  }
  const ids = new Set();
  const photos = new Set();
  for (const item of value.products) {
    if (!item || typeof item.id !== "string" || !/^\d+$/.test(item.id) || ids.has(item.id) ||
        !groups.has(item.group) || typeof item.category !== "string" || !item.category ||
        ![item.title, item.description, item.categoryLabel].every(v => typeof v === "string" && v.length > 0) ||
        typeof item.brand !== "string" || !Number.isFinite(item.price) || item.price <= 0 || item.price > 1000000 ||
        !Array.isArray(item.tags) || !item.tags.every(v => typeof v === "string") ||
        item.image !== `images/${item.id}.webp` || photos.has(item.image)) {
      throw new Error("Invalid sample product.");
    }
    ids.add(item.id);
    photos.add(item.image);
  }
  return value;
}

export function emptyPreferences() {
  return { schema: SCHEMA, viewed: [], liked: [], ratings: {} };
}

export function restorePreferences(value, products) {
  const empty = emptyPreferences();
  if (!value || value.schema !== SCHEMA || !Array.isArray(value.viewed) ||
      !Array.isArray(value.liked) || value.viewed.length > 100 || value.liked.length > 100 ||
      !value.ratings || Array.isArray(value.ratings) || typeof value.ratings !== "object" ||
      Object.keys(value.ratings).length > 100) return empty;
  const ids = new Set(products.map(item => item.id));
  const valid = id => typeof id === "string" && ids.has(id);
  if (!value.viewed.every(valid) || !value.liked.every(valid) ||
      !Object.entries(value.ratings).every(([id, rating]) => valid(id) && Number.isInteger(rating) && RATINGS.has(rating))) {
    return empty;
  }
  const ratings = { ...value.ratings };
  return {
    schema: SCHEMA,
    viewed: [...new Set(value.viewed)],
    liked: [...new Set(value.liked)].filter(id => !(ratings[id] <= 2)),
    ratings,
  };
}

export function preferenceCount(state) {
  return new Set([...state.viewed, ...state.liked, ...Object.keys(state.ratings)]).size;
}

function overlap(left, right) {
  const a = new Set(left);
  const b = new Set(right);
  const union = new Set([...a, ...b]).size;
  return union ? [...a].filter(tag => b.has(tag)).length / union : 0;
}

function signal(state, id) {
  const rating = state.ratings[id];
  // Explicit low ratings dominate a prior view; a neutral rating adds no view signal.
  if (rating !== undefined && rating <= 3) return RATINGS.get(rating);
  return (state.viewed.includes(id) ? 0.5 : 0) +
    (state.liked.includes(id) ? 3 : 0) + (RATINGS.get(rating) ?? 0);
}

export function recommend(products, input, limit = 12) {
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) throw new RangeError("limit must be an integer in [1, 100]");
  const state = restorePreferences(input, products);
  const engaged = new Set([...state.viewed, ...state.liked, ...Object.keys(state.ratings)]);
  const anchors = products.map(item => ({ item, weight: signal(state, item.id) })).filter(row => row.weight !== 0);
  const positive = anchors.filter(row => row.weight > 0);
  const normalizer = anchors.reduce((sum, row) => sum + Math.abs(row.weight), 0) || 1;
  const ranked = products.filter(item => !engaged.has(item.id)).map((item, index) => {
    let score = 0;
    let strongest = null;
    let strongestContribution = 0;
    for (const anchor of anchors) {
      const sameGroup = item.group === anchor.item.group;
      const similarity = 0.5 * Number(item.category === anchor.item.category) +
        0.25 * Number(sameGroup) + 0.15 * Number(FAMILIES[item.group] === FAMILIES[anchor.item.group]) +
        0.1 * overlap(item.tags, anchor.item.tags);
      const contribution = anchor.weight * similarity;
      score += contribution;
      if (contribution > strongestContribution) {
        strongest = anchor.item;
        strongestContribution = contribution;
      }
    }
    score /= normalizer;
    const groupPositive = positive.filter(row => row.item.group === item.group);
    if (groupPositive.length) {
      const total = groupPositive.reduce((sum, row) => sum + row.weight, 0);
      const budget = groupPositive.reduce((sum, row) => sum + row.item.price * row.weight, 0) / total;
      score += 0.08 * Math.exp(-Math.abs(Math.log(item.price / budget)));
    }
    const reason = strongest
      ? { type: "similar", anchorId: strongest.id, text: `Inspired by ${strongest.title}` }
      : { type: "discovery", anchorId: null, text: anchors.length ? "Explore something different" : "A discovery pick from the sample catalog" };
    return { item, score, reason, index };
  });
  ranked.sort((a, b) => b.score - a.score || a.index - b.index || a.item.id.localeCompare(b.item.id, "en"));
  // Limit a group to six slots when alternatives exist; then fill remaining slots.
  const selected = [];
  const counts = new Map();
  for (const row of ranked) {
    if ((counts.get(row.item.group) ?? 0) >= 6) continue;
    selected.push(row);
    counts.set(row.item.group, (counts.get(row.item.group) ?? 0) + 1);
    if (selected.length === limit) break;
  }
  if (selected.length < limit) {
    const chosen = new Set(selected.map(row => row.item.id));
    for (const row of ranked) {
      if (!chosen.has(row.item.id)) selected.push(row);
      if (selected.length === limit) break;
    }
  }
  return selected.map(({ item, score, reason }) => ({ item, score, reason }));
}
