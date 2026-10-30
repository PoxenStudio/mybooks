export const HOMEPAGE_VERSION = 1;

export const BUILTIN_SECTIONS = [
  "libraryStats",
  "readingStats",
  "index.myReading",
  "index.socialRecommendation",
  "index.booklistRecommendation",
  "index.randomRecommendation",
  "index.newRecommendation",
];

export const SECTION_META = {
  libraryStats: { icon: "mdi-chart-bar", label: "settings.homepage_section_library_stats" },
  readingStats: { icon: "mdi-chart-line", label: "settings.homepage_section_reading_stats" },
  "index.myReading": { icon: "mdi-book-open-page-variant-outline", label: "index.myReading" },
  "index.socialRecommendation": { icon: "mdi-star-check", label: "index.socialRecommendation" },
  "index.booklistRecommendation": { icon: "mdi-format-list-bulleted-square", label: "index.booklistRecommendation" },
  "index.randomRecommendation": { icon: "mdi-apple-keyboard-command", label: "index.randomRecommendation" },
  "index.newRecommendation": { icon: "mdi-hexagram-outline", label: "index.newRecommendation" },
};

// 首页内置卡片 ↔ 功能模块（与后端 webserver/base/homepage.py 的 CARD_MODULES 对应）。
// 模块关闭时编辑器里不出现这张卡，但不会从 order 中删除，配置原样保留。
export const SECTION_MODULE = {
  "index.booklistRecommendation": "community",
};

export const CUSTOM_TYPES = ["author", "tag", "series", "language", "rating"];
export const CUSTOM_SORTS = ["new", "title", "rating", "series", "random"];
export const CUSTOM_LIMITS = [6, 12, 24, 48];
export const MAX_CUSTOM_CARDS = 30;
export const MAX_VALUE_LEN = 200;

export function defaultSortFor(type) {
  if (type === "series") return "series";
  if (type === "rating") return "rating";
  return "new";
}

export function defaultHomepageConfig() {
  return {
    version: HOMEPAGE_VERSION,
    order: [...BUILTIN_SECTIONS],
    hidden: [],
    custom: [],
  };
}

export function cardSectionKey(card) {
  return "custom:" + card.id;
}

function cleanText(value, limit) {
  if (value === null || value === undefined) return "";
  return String(value).trim().slice(0, limit);
}

export function normalizeHomepageConfig(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return defaultHomepageConfig();
  }

  const custom = [];
  const usedIds = new Set();
  const rawCustom = Array.isArray(raw.custom) ? raw.custom : [];
  rawCustom.forEach((item, index) => {
    if (custom.length >= MAX_CUSTOM_CARDS) return;
    if (!item || typeof item !== "object") return;
    const type = cleanText(item.type, 20).toLowerCase();
    if (!CUSTOM_TYPES.includes(type)) return;
    const value = cleanText(item.value, MAX_VALUE_LEN);
    let id = cleanText(item.id, 40);
    if (!/^[A-Za-z0-9_-]{1,40}$/.test(id) || usedIds.has(id)) {
      id = "c" + (index + 1);
      while (usedIds.has(id)) id += "x";
    }
    let sort = cleanText(item.sort, 20).toLowerCase();
    if (!CUSTOM_SORTS.includes(sort)) sort = defaultSortFor(type);
    let limit = Number(item.limit);
    if (!CUSTOM_LIMITS.includes(limit)) limit = 12;
    custom.push({
      id,
      type,
      value,
      sort,
      limit,
    });
    usedIds.add(id);
  });

  const known = new Set(BUILTIN_SECTIONS);
  custom.forEach((card) => known.add(cardSectionKey(card)));

  const order = [];
  const rawOrder = Array.isArray(raw.order) ? raw.order : [];
  rawOrder.forEach((section) => {
    if (typeof section === "string" && known.has(section) && !order.includes(section)) {
      order.push(section);
    }
  });
  BUILTIN_SECTIONS.forEach((section) => {
    if (!order.includes(section)) order.push(section);
  });
  custom.forEach((card) => {
    const section = cardSectionKey(card);
    if (!order.includes(section)) order.push(section);
  });

  const hidden = [];
  const rawHidden = Array.isArray(raw.hidden) ? raw.hidden : [];
  rawHidden.forEach((section) => {
    if (typeof section === "string" && known.has(section) && !hidden.includes(section)) {
      hidden.push(section);
    }
  });

  return { version: HOMEPAGE_VERSION, order, hidden, custom };
}

export function sectionLabel(card, t) {
  if (!card) return "";
  let value = card.value;
  if (value && card.type === "rating") {
    value = t("settings.homepage_rating_value", { n: value });
  }
  if (!value) value = t("settings.homepage_card_no_value");
  return t("settings.homepage_card_auto_title", {
    type: t("settings.homepage_type_" + card.type),
    value,
  });
}

export function customCardViewAll(card) {
  return `/${card.type}/${encodeURIComponent(card.value || "")}`;
}
