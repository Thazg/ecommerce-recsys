import { emptyPreferences, preferenceCount, recommend, restorePreferences, validateCatalog } from "./recommendations.mjs";

const $ = selector => document.querySelector(selector);
const KEY = "recolens-shopping-session-v1";
const money = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" });
const HEART = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M20.8 4.6a5.4 5.4 0 0 0-7.6 0L12 5.8l-1.2-1.2a5.4 5.4 0 0 0-7.6 7.6L12 21l8.8-8.8a5.4 5.4 0 0 0 0-7.6Z"/></svg>';
const STAR = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m12 3 2.8 5.7 6.3.9-4.6 4.4 1.1 6.3-5.6-3-5.6 3 1.1-6.3L3 9.6l6.2-.9Z"/></svg>';
let catalog;
let state = emptyPreferences();
let group = "all";
let pageSize = 20;
let outputs = null;
let activeItem = null;
let toastTimer;
let storageAvailable = true;
let restoreProductFocus = true;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function toast(message) {
  clearTimeout(toastTimer);
  $("#toast").textContent = message;
  toastTimer = setTimeout(() => { $("#toast").textContent = ""; }, 3000);
}

function photo(item, className = "") {
  const image = node("img", className);
  image.src = item.image;
  image.alt = item.title;
  image.width = 300;
  image.height = 300;
  image.loading = "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => {
    image.classList.add("image-failed");
    image.src = "favicon.svg";
    image.alt = `Image unavailable: ${item.title}`;
  }, { once: true });
  return image;
}

function persist() {
  try { sessionStorage.setItem(KEY, JSON.stringify(state)); }
  catch { storageAvailable = false; }
}

function sync() {
  persist();
  const count = preferenceCount(state);
  $("#preference-count").textContent = count;
  if (outputs) $("#stale-notice").hidden = false;
  renderCatalog();
  if (outputs) renderRecommendations();
}

function like(id) {
  const focusGrid = document.activeElement?.closest("#product-grid, #recommendation-grid")?.id;
  const liked = state.liked.includes(id);
  state.liked = liked ? state.liked.filter(value => value !== id) : [...state.liked, id];
  if (!liked && state.ratings[id] <= 2) delete state.ratings[id];
  sync();
  if (focusGrid) $("#" + focusGrid).querySelector(`[data-like="${id}"]`)?.focus({ preventScroll: true });
  if (activeItem?.id === id) renderDetail();
  toast(liked ? "Removed from your favorites" : "Added to your favorites");
}

function card(item, reason) {
  const article = node("article", "product-card");
  article.dataset.product = item.id;
  const open = node("button", "product-open");
  open.type = "button";
  open.dataset.open = item.id;
  open.setAttribute("aria-label", `View ${item.title}`);
  const visual = node("span", "product-visual");
  visual.append(photo(item));
  open.append(visual, node("span", "product-category", item.categoryLabel),
    node("h3", "product-name", item.title), node("span", "product-price", money.format(item.price)));
  article.append(open);
  const heart = node("button", "like-button");
  heart.type = "button";
  heart.dataset.like = item.id;
  heart.innerHTML = HEART;
  heart.setAttribute("aria-label", `${state.liked.includes(item.id) ? "Unsave" : "Save"} ${item.title}`);
  heart.setAttribute("aria-pressed", String(state.liked.includes(item.id)));
  article.append(heart);
  if (state.ratings[item.id]) {
    const rating = node("span", "rating-label");
    rating.innerHTML = STAR;
    rating.append(document.createTextNode(` Your rating: ${state.ratings[item.id]}/5`));
    article.append(rating);
  }
  if (reason) article.append(node("p", "product-reason", reason.text));
  return article;
}

function normalize(text) {
  return text.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

function renderCatalog() {
  if (!catalog) return;
  const query = normalize($("#search").value.trim());
  const sorting = $("#sort").value;
  let products = catalog.products.filter(item => (group === "all" || item.group === group) &&
    normalize(`${item.title} ${item.categoryLabel} ${item.brand} ${catalog.groups.find(row => row.id === item.group).label}`).includes(query) &&
    (sorting !== "liked" || state.liked.includes(item.id)));
  if (sorting === "price-asc") products.sort((a, b) => a.price - b.price || Number(a.id) - Number(b.id));
  if (sorting === "price-desc") products.sort((a, b) => b.price - a.price || Number(a.id) - Number(b.id));
  $("#product-grid").replaceChildren(...products.slice(0, pageSize).map(item => card(item)));
  $("#product-grid").setAttribute("aria-busy", "false");
  $("#catalog-count").textContent = `${products.length} products${group !== "all" || query || sorting === "liked" ? " found" : " to explore"}`;
  $("#visible-count").textContent = products.length ? `Showing ${Math.min(pageSize, products.length)} of ${products.length} products` : "";
  $("#load-more").hidden = pageSize >= products.length;
  $("#catalog-empty").hidden = products.length !== 0;
  $("#clear-search").hidden = !query;
}

function renderCategories() {
  const buttons = [{ id: "all", label: "All products" }, ...catalog.groups].map(row => {
    const button = node("button", "category-chip", row.label);
    button.type = "button";
    button.dataset.group = row.id;
    button.setAttribute("aria-pressed", String(row.id === group));
    return button;
  });
  $("#categories").replaceChildren(...buttons);
}

function renderRecommendations() {
  $("#recommendation-grid").replaceChildren(...outputs.map(row => card(row.item, row.reason)));
}

function generate() {
  if (!catalog) return;
  if ($("#product-dialog").open) restoreProductFocus = false;
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  outputs = recommend(catalog.products, state);
  $("#recommendations").hidden = false;
  $("#stale-notice").hidden = true;
  $("#recommendation-empty").hidden = outputs.length !== 0;
  const hasPositive = state.liked.length || Object.values(state.ratings).some(rating => rating >= 4);
  const hasSignal = state.viewed.some(id => state.ratings[id] === undefined) || hasPositive || Object.values(state.ratings).some(rating => rating <= 2);
  $("#recommendation-title").textContent = hasSignal ? "More to your taste." : "A little inspiration.";
  $("#recommendation-description").textContent = hasSignal
    ? `${outputs.length} picks based on this session. Products you have interacted with are excluded.`
    : "No preferences yet. Explore a mix of categories, then save or rate products to make these picks your own.";
  renderRecommendations();
  $("#recommendations").scrollIntoView({ behavior: "instant", block: "start" });
  $("#recommendation-title").focus({ preventScroll: true });
}

function openProduct(id) {
  activeItem = catalog.products.find(item => item.id === id);
  if (!activeItem) return;
  if (!state.viewed.includes(id)) {
    state.viewed.push(id);
    sync();
  }
  renderDetail();
  $("#product-dialog").showModal();
}

function renderDetail() {
  const item = activeItem;
  const layout = node("div", "product-detail-layout");
  const visual = node("div", "detail-photo");
  visual.append(photo(item));
  const copy = node("div", "detail-copy");
  const title = node("h2", "", item.title);
  title.id = "product-title";
  copy.append(node("p", "detail-category", item.categoryLabel), title,
    node("p", "detail-price", money.format(item.price)), node("p", "price-note", "USD · Sample price, not an offer"),
    node("p", "detail-description", item.description));
  const field = node("fieldset", "rating-field");
  field.append(node("legend", "", "How well does this fit your taste?"));
  const stars = node("div", "stars");
  stars.setAttribute("role", "group");
  stars.setAttribute("aria-label", "Rate from 1 to 5 stars");
  for (let value = 1; value <= 5; value++) {
    const button = node("button", `star-button${value <= (state.ratings[item.id] ?? 0) ? " filled" : ""}`);
    button.type = "button";
    button.innerHTML = STAR;
    button.setAttribute("aria-label", `Rate ${value} ${value === 1 ? "star" : "stars"}`);
    button.setAttribute("aria-pressed", String(state.ratings[item.id] === value));
    button.addEventListener("click", () => {
      if (state.ratings[item.id] === value) delete state.ratings[item.id];
      else state.ratings[item.id] = value;
      if (value <= 2) state.liked = state.liked.filter(id => id !== item.id);
      sync();
      renderDetail();
      $("#product-detail").querySelectorAll(".star-button")[value - 1].focus();
    });
    stars.append(button);
  }
  const rating = state.ratings[item.id];
  field.append(stars, node("p", "rating-help", rating
    ? `Your rating: ${rating}/5 · Select again to clear`
    : "1–2: Not for me · 3: Neutral · 4–5: Like it"));
  const actions = node("div", "detail-actions");
  const heart = node("button", "button secondary", state.liked.includes(item.id) ? "Saved" : "Save to favorites");
  heart.type = "button";
  heart.setAttribute("aria-pressed", String(state.liked.includes(item.id)));
  heart.addEventListener("click", () => { like(item.id); $("#product-detail .detail-actions button").focus(); });
  const more = node("button", "button primary", "Get recommendations");
  more.type = "button";
  more.addEventListener("click", generate);
  actions.append(heart, more);
  copy.append(field, actions);
  layout.append(visual, copy);
  $("#product-detail").replaceChildren(layout);
}

function preferences() {
  const count = preferenceCount(state);
  $("#preferences-summary").textContent = count
    ? `${count} explored · ${state.liked.length} saved · ${Object.keys(state.ratings).length} rated`
    : "A fresh start. Save or rate a few products to discover your preferences.";
  const interacted = new Set([...state.viewed, ...state.liked, ...Object.keys(state.ratings)]);
  const rows = catalog.products.filter(item => interacted.has(item.id)).map(item => {
    const row = node("div", "preference-row");
    const info = node("div");
    const labels = [state.liked.includes(item.id) ? "Saved" : "", state.ratings[item.id] ? `${state.ratings[item.id]}/5 stars` : "", state.viewed.includes(item.id) ? "Viewed" : ""].filter(Boolean);
    info.append(node("strong", "", item.title), node("span", "", labels.join(" · ")));
    const remove = node("button", "remove-preference", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", `Remove activity for ${item.title}`);
    remove.addEventListener("click", () => {
      state.viewed = state.viewed.filter(id => id !== item.id);
      state.liked = state.liked.filter(id => id !== item.id);
      delete state.ratings[item.id];
      sync(); preferences(); $("#reset-preferences").focus();
    });
    row.append(photo(item), info, remove);
    return row;
  });
  $("#preference-list").replaceChildren(...rows);
  $("#storage-notice").textContent = storageAvailable
    ? "Stored only in this tab session. Your activity is not sent to a server."
    : "Session storage is unavailable. Your preferences will last until you reload this page.";
  $("#reset-preferences").disabled = count === 0;
}

for (const id of ["product", "preferences", "how"]) {
  const dialog = $(`#${id}-dialog`);
  $(`#close-${id}`).addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", event => {
    if (event.target !== dialog) return;
    const box = dialog.getBoundingClientRect();
    if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) dialog.close();
  });
}
$("#product-dialog").addEventListener("close", () => {
  if (activeItem && restoreProductFocus) $("#product-grid").querySelector(`[data-open="${activeItem.id}"]`)?.focus({ preventScroll: true });
  activeItem = null;
  restoreProductFocus = true;
});
$("#understood").addEventListener("click", () => $("#how-dialog").close());
$("#how-button").addEventListener("click", () => $("#how-dialog").showModal());
for (const id of ["hero-recommend", "refresh-recommend", "preferences-recommend"]) $("#" + id).addEventListener("click", generate);
$("#preferences-button").addEventListener("click", () => {
  if (!catalog) return;
  preferences(); $("#preferences-dialog").showModal();
});
for (const id of ["product-grid", "recommendation-grid"]) $("#" + id).addEventListener("click", event => {
  const heart = event.target.closest("[data-like]");
  const open = event.target.closest("[data-open]");
  if (heart) like(heart.dataset.like);
  else if (open) openProduct(open.dataset.open);
});
$("#categories").addEventListener("click", event => {
  const button = event.target.closest("[data-group]");
  if (!button) return;
  group = button.dataset.group; pageSize = 20;
  for (const element of $("#categories").children) element.setAttribute("aria-pressed", String(element === button));
  renderCatalog();
});
$(".hero-collection").addEventListener("click", event => {
  const button = event.target.closest("[data-collection]");
  if (!catalog || !button || button.disabled) return;
  group = button.dataset.collection;
  pageSize = 20;
  $("#search").value = "";
  $("#sort").value = "discovery";
  renderCategories();
  renderCatalog();
  $("#categories").querySelector('[aria-pressed="true"]')?.scrollIntoView({ behavior: "instant", block: "nearest", inline: "nearest" });
  $("#catalog").scrollIntoView({ behavior: "instant", block: "start" });
  $("#catalog-title").focus({ preventScroll: true });
});
$(".search-form").addEventListener("submit", event => { event.preventDefault(); $("#catalog").scrollIntoView({ behavior: "instant" }); });
$("#search").addEventListener("input", () => { pageSize = 20; renderCatalog(); });
$("#clear-search").addEventListener("click", () => { $("#search").value = ""; pageSize = 20; renderCatalog(); $("#search").focus(); });
$("#sort").addEventListener("change", () => { pageSize = 20; renderCatalog(); });
$("#load-more").addEventListener("click", () => { pageSize += 20; renderCatalog(); });
$("#clear-filters").addEventListener("click", () => {
  group = "all"; pageSize = 20; $("#search").value = ""; $("#sort").value = "discovery";
  renderCategories(); renderCatalog();
});
$("#reset-preferences").addEventListener("click", () => {
  state = emptyPreferences(); outputs = null; $("#recommendations").hidden = true;
  sync(); preferences(); toast("Preferences cleared. Try a different style.");
  $("#preferences-recommend").focus();
});

async function initialize() {
  for (const button of document.querySelectorAll("#hero-recommend, #preferences-button")) button.disabled = true;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch("catalog.json", { signal: controller.signal });
    if (!response.ok) throw new Error("Catalog unavailable");
    const text = await response.text();
    if (text.length > 300000) throw new Error("Catalog too large");
    catalog = validateCatalog(JSON.parse(text));
    try { state = restorePreferences(JSON.parse(sessionStorage.getItem(KEY)), catalog.products); }
    catch { state = emptyPreferences(); storageAvailable = false; }
    renderCategories(); sync();
    const heroes = [["#hero-tech", "accessories"], ["#hero-fashion", "men"], ["#hero-home", "home"]];
    for (const [selector, slug] of heroes) {
      const item = catalog.products.find(row => row.group === slug && (slug !== "men" || row.category === "mens-shoes"));
      $(selector).src = item.image;
      $(selector).alt = item.title;
    }
    for (const button of document.querySelectorAll("#hero-recommend, #preferences-button")) button.disabled = false;
    for (const button of document.querySelectorAll("[data-collection]")) button.disabled = false;
  } catch {
    $("#load-error").hidden = false;
    $("#catalog-count").textContent = "Catalog unavailable";
    $("#product-grid").setAttribute("aria-busy", "false");
  } finally { clearTimeout(timer); }
}
initialize();
