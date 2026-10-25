# RecoMe shopping demonstration

## Purpose

RecoMe is a small storefront that makes personalization tangible:
browse photographed products, express a preference and request new suggestions.
It uses a separate sample catalog rather than assigning invented photographs
or product names to anonymized Retailrocket IDs.

The interface is in English. The catalog contains **100 products across ten
groups**, including technology, fashion, beauty, home and groceries. Product
names, descriptions and sample USD prices come from
[DummyJSON](https://dummyjson.com/docs/products). No seller, stock, review,
sales or payment claim is made.

## Run locally

The public demo is [shoprecome.vercel.app](https://shoprecome.vercel.app/).
It runs without an operator's local machine or recommendation API.

From the repository root:

```sh
conda activate ecommerce-recsys
python -m http.server 8766 --bind 127.0.0.1 --directory shop-demo
```

Open `http://127.0.0.1:8766/`. Serve only `shop-demo/`, not the repository root.
No model bundle, API, API credential, package installation or build step is
needed. The local snapshot model can continue independently on port 8000.

1. Open a product to inspect its photograph and sample description.
2. Use a heart or a 1–5 rating to express a preference.
3. Select **Get recommendations** to receive up to twelve unseen suggestions.
4. Inspect the reason below each product; change preferences and update results.
5. Use **Your preferences** to remove individual signals or reset the entire session.

Search accepts product names, brands and English category labels, with
accent-insensitive matching. Category filters, price sorting, a saved-only view and incremental
catalog loading are available. A zero-result search and an exhausted catalog
have explicit empty states.

## Illustrative policy

The policy is content-based JavaScript, computed in the browser. It is a small,
explainable interaction demonstration, **not the trained Retailrocket model**.

| Signal | Weight |
| :--- | ---: |
| View a distinct product | 0.5 |
| Heart | +3 |
| Rate 1 / 2 / 3 / 4 / 5 | −6 / −3 / 0 / +3 / +6 |

Views do not accumulate when reopening a product. Explicit ratings of 1–3
replace the view signal; a low rating removes a conflicting heart. Adding a
heart later clears a conflicting low rating. Positive ratings may combine
with a heart and one view.

For each unengaged candidate, similarity to each signaled product is:

```text
0.50 × same subcategory
+ 0.25 × same catalog group
+ 0.15 × same related-group family
+ 0.10 × tag Jaccard similarity
```

Digital devices and digital accessories share a family; fashion groups share
another; home and kitchen share another. Beauty, sports and food each retain
their own family. These relationships describe broad interests, not device
compatibility or complementary-product guarantees.

The weighted similarity sum is divided by the total absolute signal weight.
A same-group positive preference adds a bounded price-affinity term,
`0.08 × exp(−abs(log(candidate_price / preferred_price)))`, where preferred
price is the positive signal-weighted mean. Negative signals reduce priority.
Ties follow the fixed catalog order. A greedy pass limits each group to six
suggestions when alternatives exist; a second pass fills any remaining slots.

All products viewed, hearted or rated are excluded from new results, including
neutral and disliked products. Reasons identify a positively contributing
anchor or label the result as discovery. With no nonzero signal, a varied
catalog-order list is explicitly labeled **not yet personalized**. Results
are computed on button press; later edits mark the displayed list as stale.

No collaborative learning, training, session model, benchmark accuracy,
conversion uplift or production recommendation quality is claimed.

## Data and privacy

The [catalog](../shop-demo/catalog.json) contains a curated sample from the
DummyJSON product endpoint. All 100 WebP thumbnails are stored locally, totaling
927,394 bytes. [Image sources](../shop-demo/image_sources.json) record each
upstream URL, byte length and SHA-256. The
[third-party notice](../shop-demo/THIRD_PARTY_NOTICES.txt) retains the upstream
repository license and attribution. Product marks belong to their owners;
there is no seller affiliation.

Images, modules and catalog load from the same origin. No analytics,
external fonts, recommendation API requests or third-party image requests are
made during use. Preferences use `sessionStorage` in the current tab; storage
failure falls back to memory with a visible explanation in the preferences
panel. Nothing sends interaction history to a server. Browser session restore
or a duplicated tab can preserve session storage; use the reset button for a
fresh demonstration. Browser caching and the static server's ordinary request
logs remain browser/server behavior.

The page sets a restrictive meta Content Security Policy. The separate Vercel
release adds response-level CSP, framing denial, MIME protection, referrer and
permissions controls. The original snapshot-explorer deployment is unchanged.

## Static publication

The `shoprecome` project uses Vercel Hobby and the free `shoprecome.vercel.app`
address. An explicit CLI release uploads 108 reviewed public files plus a
static-host configuration, with no build/install commands or Git integration.
The upload is staged outside the repository; model files, raw data, credentials
and private helpers are excluded. This does not deploy the Retailrocket API.

The [hosting verification](../benchmarks/demo/shopping_hosting_validation_v1.json)
records deployed asset hashes, response headers, anonymous access and private-path
404 checks. These are point-in-time functional checks, not an availability SLA.
Future releases require a fresh reviewed allowlist and separate evidence;
root Vercel configuration continues to belong to the original snapshot explorer.

## Verification and boundaries

```sh
node --test --test-isolation=none tests/web/test_shopping_demo.mjs
node --check shop-demo/app.mjs
```

The ten Node cases cover all image hashes and distinct image bytes, deterministic
cold discovery, preference-dependent output, full interaction exclusion, negative
and neutral ratings, group diversity, corrupted session data, exhausted pools,
invalid output budgets and unsafe catalog fields. The tests need no network,
model or npm dependencies. Node 24 was used locally.

The browser walkthrough checks the actual view/rating/recommendation flow,
hearts and stale-result feedback, empty search, filters, full 100-product
browsing, session reset and responsive layouts. These are functional checks
of a sample interface, not measurements of accuracy or an availability SLA.

The [snapshot explorer](SNAPSHOT_EXPLORER.md) remains the separate interface to
verified historical model outputs. The [local model guide](LOCAL_DEMONSTRATION.md)
describes real Retailrocket inference. The shopping illustration does not
change either model evidence or the open cloud/target-host gates.
