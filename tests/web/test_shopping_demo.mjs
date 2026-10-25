import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { emptyPreferences, preferenceCount, recommend, restorePreferences, validateCatalog } from "../../shop-demo/recommendations.mjs";

const root = new URL("../../shop-demo/", import.meta.url);
const catalog = validateCatalog(JSON.parse(await readFile(new URL("catalog.json", root), "utf8")));
const products = catalog.products;
const sources = JSON.parse(await readFile(new URL("image_sources.json", root), "utf8"));
const preference = (item, rating = 5) => ({ ...emptyPreferences(), viewed: [item.id], ratings: { [item.id]: rating } });

test("catalog has 100 distinct usable local WebP photos with independently pinned source bytes", async () => {
  assert.equal(sources.images.length, 100);
  assert.equal(new Set(sources.images.map(row => row.path)).size, 100);
  assert.equal(new Set(sources.images.map(row => row.sha256)).size, 100);
  for (const item of products) {
    const record = sources.images.find(row => row.path === item.image);
    assert.equal(record.source, item.imageSource);
    assert.match(record.source, /^https:\/\/cdn\.dummyjson\.com\/product-images\//);
    const bytes = await readFile(new URL(item.image, root));
    assert.equal(bytes.subarray(0, 4).toString(), "RIFF");
    assert.equal(bytes.subarray(8, 12).toString(), "WEBP");
    assert.equal(bytes.length, record.bytes);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), record.sha256);
  }
  assert.equal(new Set(products.map(item => item.group)).size, 10);
});

test("new shoppers receive deterministic varied discovery without invented personalization", () => {
  const first = recommend(products, emptyPreferences());
  assert.deepEqual(first, recommend(products, emptyPreferences()));
  assert.equal(first.length, 12);
  assert.equal(new Set(first.map(row => row.item.id)).size, 12);
  assert.ok(first.every(row => row.reason.type === "discovery"));
  assert.ok(new Set(first.map(row => row.item.group)).size >= 8);
});

test("changing a strong preference from technology to fashion changes the actual output", () => {
  const tech = products.find(item => item.group === "tech");
  const fashion = products.find(item => item.group === "women");
  const forTech = recommend(products, preference(tech));
  const forFashion = recommend(products, preference(fashion));
  assert.equal(forTech[0].item.group, "tech");
  assert.equal(forFashion[0].item.group, "women");
  assert.notDeepEqual(forTech.map(row => row.item.id), forFashion.map(row => row.item.id));
  assert.equal(forTech[0].reason.anchorId, tech.id);
});

test("viewed, liked and rated products are all excluded, including neutral and negative ratings", () => {
  const state = { ...emptyPreferences(), viewed: [products[0].id], liked: [products[1].id], ratings: { [products[2].id]: 1, [products[3].id]: 3 } };
  const blocked = new Set(products.slice(0, 4).map(item => item.id));
  assert.equal(preferenceCount(state), 4);
  assert.ok(recommend(products, state).every(row => !blocked.has(row.item.id)));
});

test("explicit dislike demotes similar content and neutral rating removes view preference", () => {
  const item = products.find(row => row.group === "tech");
  const disliked = recommend(products, preference(item, 1), 100);
  const neutral = recommend(products, preference(item, 3));
  const peers = disliked.filter(row => row.item.category === item.category);
  assert.ok(peers.every(row => row.score < 0));
  assert.ok(neutral.every(row => row.reason.type === "discovery" && row.score === 0));
});

test("strong preferences retain multiple groups and explain every positive match", () => {
  const tech = products.find(item => item.group === "tech");
  const state = preference(tech);
  const rows = recommend(products, state);
  assert.equal(rows.filter(row => row.item.group === "tech").length, 6);
  assert.ok(new Set(rows.map(row => row.item.group)).size >= 2);
  for (const row of rows.filter(row => row.reason.type === "similar")) {
    assert.equal(row.reason.anchorId, tech.id);
    assert.ok(row.score > 0);
  }
});

test("corrupt, unknown, stale or excessive session data is discarded", () => {
  for (const bad of [null, [], { schema: "old" }, { ...emptyPreferences(), liked: ["unknown"] },
    { ...emptyPreferences(), ratings: { [products[0].id]: true } },
    { ...emptyPreferences(), ratings: { [products[0].id]: NaN } },
    { ...emptyPreferences(), viewed: Array(101).fill(products[0].id) }]) {
    assert.deepEqual(restorePreferences(bad, products), emptyPreferences());
  }
  const conflict = { ...preference(products[0], 1), liked: [products[0].id] };
  assert.deepEqual(restorePreferences(conflict, products).liked, []);
});

test("exhausted and nearly exhausted catalogs return honest short outputs without mutating preferences", () => {
  const full = { ...emptyPreferences(), viewed: products.map(item => item.id) };
  const before = structuredClone(full);
  assert.deepEqual(recommend(products, full), []);
  full.viewed.pop();
  assert.equal(recommend(products, full).length, 1);
  assert.equal(before.viewed.length, 100);
  assert.equal(full.viewed.length, 99);
});

test("limits reject booleans, fractions, NaN, zero and oversized output budgets", () => {
  for (const limit of [true, 1.5, NaN, 0, -1, 101]) assert.throws(() => recommend(products, emptyPreferences(), limit), RangeError);
});

test("unsafe image paths, nonfinite prices, duplicate IDs and category drift fail closed", () => {
  for (const edit of [value => { value.products[0].image = "../AGENTS.md"; },
    value => { value.products[0].price = NaN; },
    value => { value.products[1].id = value.products[0].id; },
    value => { value.products[0].group = "nonexistent"; }]) {
    const value = structuredClone(catalog); edit(value);
    assert.throws(() => validateCatalog(value));
  }
});
