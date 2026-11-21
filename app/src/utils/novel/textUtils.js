/* eslint-disable no-useless-escape, no-irregular-whitespace -- 与上游 tools-by-ai 算法逐行一致，正则里的转义/全角空格均为刻意保留 */
const normalizeNewlines = (text) => text.includes("\r") ? text.replace(/\r\n?/g, "\n") : text;
const splitTextIntoLines = (text, options = {}) => {
  if (!text) {
    return [];
  }
  const normalized = normalizeNewlines(text);
  let lines = normalized.split("\n");
  if (options.removeEmptyLines) {
    lines = lines.filter(Boolean);
  }
  return lines;
};
const cleanLines = (text, shouldTrim = false) => splitTextIntoLines(text).filter((line) => line.trim()).map((line) => shouldTrim ? line.trim() : line);
const joinLines = (text, separator = "", shouldTrim = true) => cleanLines(text, shouldTrim).join(separator);
const MAX_DISPLAY_LENGTH = 1e5;
const truncate = (str, num = MAX_DISPLAY_LENGTH) => str.length <= num ? str : `${str.slice(0, num)}...`;
const splitCNParagraph = (text) => {
  const paragraphCNSplitRegex = /(如下：(?!\n)|[^\n“”][。；！？]”?\b(?=[A-Za-z_･]{2,11}：[^\n“])|(?:\w」?；)(?=[^\n“”：；]{14})|(?<=\w：“[^\n“”]{1,39}[。！？—…]”)(?=[^\n“”：；]{1,39}：“)|(?:[^\n【】]】)(?=【\w{1,7}：)|(?:\w[：；。！？]{1,2}[”]?)(?=[第其][一二三四五六七八九][，、]|[一二三四五六七八九][则来是者]?[，、]|[①-⓿][^\n]|（[^\n（）]{17,29}[。！？…]）\n)|(?:[^\n“”][。！？—…]”)(?:[一-龥]{1,14}[说道]。)?(?=“[^\n“”])|(?<=[^\n]{4})(?:[^\n]{24}[。！？—…][』”’】］）]?)(?=[^\n]{29})(?<![。！？—…]\w{1,4}[！？…]{1,2})(?![、，。：；！？—…]|(?<=(\w{1,3})……)\2|(?<=[—…”])[^“”。：；！？—…]{1,14}[。：；！？—…]|(?<=……)(?:[等略]|以?及|的[^的确士])|(?<=[』”’】］）])[的地]))(?<!“[^\n”]{1,34}|‘[^\n’]{1,34}|「[^\n」]{1,34}|『[^\n』]{1,34}|（[^\n）]{1,34}|【[^\n】]{1,34}|［[^\n］]{1,34})(?![^\n“]{0,34}”|[^\n‘]{0,34}’|[^\n「]{0,34}」|[^\n『]{0,34}』|[^\n（]{0,34}）|[^\n【]{0,34}】|[^\n［]{0,34}］)/g;
  return text.replace(paragraphCNSplitRegex, "$1\n");
};
const splitEnglishParagraph = async (text) => Array.from(new Intl.Segmenter("en", { granularity: "sentence" }).segment(text), (s) => s.segment.trim()).filter(Boolean).join("\n");
const splitParagraph = async (text, method = "cn") => {
  switch (method) {
    case "cn":
      return splitCNParagraph(text);
    case "en":
      return await splitEnglishParagraph(text);
  }
};
const toHalfWidth = (text) => text.replace(/[０-９Ａ-Ｚａ-ｚ]/g, (char) => String.fromCharCode(char.charCodeAt(0) - 65248));
const filterLines = (text, filters, options = {}) => {
  const { exact = false, maxLen } = options;
  const list = (Array.isArray(filters) ? filters : filters.split(/[\n,]/)).map((w) => w.trim()).filter(Boolean);
  const exactSet = exact ? new Set(list) : void 0;
  const hasMaxLen = typeof maxLen === "number" && maxLen > 0;
  return splitTextIntoLines(text).filter((line) => {
    if (hasMaxLen && line.trim().length > maxLen) return true;
    if (exactSet) return !exactSet.has(line.trim());
    return !list.some((f) => line.includes(f));
  }).join("\n");
};
const dedupeAdjacentLines = (lines) => {
  if (lines.length === 0) return lines;
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const cur = lines[i].trim();
    const prev = i > 0 ? lines[i - 1].trim() : "";
    if (i === 0 || cur !== prev) out.push(lines[i]);
  }
  return out;
};
const SENTENCE_PUNCT_ONLY = /^[？！。…，、；：?!.,;:]+$/u;
const isSeparatorBar = (s) => {
  const t = s.trim();
  return t.length >= 3 && /^[^\p{L}\p{N}\s]+$/u.test(t) && !SENTENCE_PUNCT_ONLY.test(t) && !/[\p{Emoji_Presentation}️]/u.test(t);
};
const dedupeLines = (lines, options = {}) => {
  const { trim = true } = options;
  const seen = /* @__PURE__ */ new Set();
  const out = [];
  for (const line of lines) {
    const key = trim ? line.trim() : line;
    if (!seen.has(key)) {
      seen.add(key);
      out.push(line);
    }
  }
  return out;
};
const TEMPLATE_VAR_RE = /\$(\d+)/g;
const NUMERIC_VALUE_RE = /^\d+(?:\.\d+)?$/;
const renderPairTemplate = (template, anchor, pair) => template.replace(TEMPLATE_VAR_RE, (_, digits) => {
  const idx = Number(digits);
  if (idx === 0) return anchor;
  const group = pair[idx];
  return group === void 0 ? idx === 1 ? pair[0] : "" : group;
});
const formatNumericSum = (n) => n.toFixed(6).replace(/\.?0+$/, "");
const extractPairedLines = (text, anchorRegex, pairRegex, template, shouldTrim = true) => {
  const lines = cleanLines(text, shouldTrim);
  const anchorFinder = new RegExp(anchorRegex.source, anchorRegex.flags.replace("g", ""));
  const pairFinder = new RegExp(pairRegex.source, pairRegex.flags.replace("g", ""));
  const anchorScanner = new RegExp(anchorRegex.source, anchorRegex.flags.includes("g") ? anchorRegex.flags : `${anchorRegex.flags}g`);
  const maskAnchors = (line) => {
    var _a;
    let out2 = "";
    let last = 0;
    for (const m of line.matchAll(anchorScanner)) {
      const at = (_a = m.index) != null ? _a : 0;
      out2 += line.slice(last, at) + " ".repeat(m[0].length);
      last = at + m[0].length;
    }
    return out2 + line.slice(last);
  };
  const out = [];
  let allNumeric = true;
  let sum = 0;
  for (let i = 0; i < lines.length; i++) {
    const anchorMatch = anchorFinder.exec(lines[i]);
    if (!anchorMatch) continue;
    const anchor = anchorMatch[0];
    let pair = pairFinder.exec(maskAnchors(lines[i]));
    if (!pair && i + 1 < lines.length) pair = pairFinder.exec(maskAnchors(lines[i + 1]));
    if (!pair) continue;
    out.push(renderPairTemplate(template, anchor, pair));
    const value = pair[1];
    if (value === void 0 || !NUMERIC_VALUE_RE.test(value)) {
      allNumeric = false;
    } else {
      sum += Number(value);
    }
  }
  const total = allNumeric && out.length > 0 ? formatNumericSum(sum) : null;
  return { lines: out, total };
};
const compressNewlinesRegexCache = /* @__PURE__ */ new Map();
const compressNewlines = (text, maxConsecutive = 2) => {
  if (maxConsecutive < 1) return text.replace(/\n+/g, "\n");
  let re = compressNewlinesRegexCache.get(maxConsecutive);
  if (!re) {
    re = new RegExp(`\\n{${maxConsecutive + 1},}`, "g");
    compressNewlinesRegexCache.set(maxConsecutive, re);
  }
  return text.replace(re, "\n".repeat(maxConsecutive));
};
const CLI_GUTTER_RE = /^([ \t]*)(?:[>▏▎▍▌▐█│┃┆┊║]\s?)+/;
const CJK_CHAR_RE = /[\u00B7\u2014\u2018-\u201D\u2026　-ヿ㐀-鿿豈-﫿＀-￯]/;
const CJK_NO_SPACE_AFTER_RE = /[，。！？：；、）》】」』”’…—～]/;
const CJK_NO_SPACE_BEFORE_RE = /[，。！？：；、）》】」』”’…—～（《【「『“‘]/;
const LIST_ITEM_RE = /^\s*(?:[-*+]|\d+[.)])\s+/;
const TABLE_ROW_RE = /^\s*\|/;
const CODE_FENCE_RE = /^\s*```/;
const HEADING_RE = /^\s*#{1,6}\s+\S/;
const HR_BANNER_RE = /^\s*(?:[-*_=][ \t]*){3,}$/;
const BOLD_LABEL_RE = /^\s*\*\*[^*]+\*\*[:：]?\s*$/;
const isCJKChar = (ch) => !!ch && CJK_CHAR_RE.test(ch);
const shouldOmitSpace = (prevChar, nextChar) => {
  if (!prevChar || !nextChar) return true;
  return isCJKChar(prevChar) && isCJKChar(nextChar) || CJK_NO_SPACE_AFTER_RE.test(prevChar) || CJK_NO_SPACE_BEFORE_RE.test(nextChar);
};
const joinParagraphFragments = (fragments) => {
  let acc = "";
  for (const fragment of fragments) {
    if (!acc) {
      acc = fragment.trimEnd();
      continue;
    }
    const prev = acc.trimEnd();
    const next = fragment.trim();
    if (!next) {
      acc = prev;
      continue;
    }
    const noSpace = shouldOmitSpace(prev[prev.length - 1], next[0]);
    acc = prev + (noSpace ? "" : " ") + next;
  }
  return acc;
};
const cleanCliText = (raw) => {
  const deGuttered = splitTextIntoLines(raw).map((line) => line.replace(CLI_GUTTER_RE, "$1"));
  const indents = deGuttered.filter((line) => line.trim()).map((line) => {
    var _a, _b;
    return (_b = (_a = line.match(/^[ \t]*/)) == null ? void 0 : _a[0].length) != null ? _b : 0;
  });
  const minIndent = indents.length ? indents.reduce((min, n) => Math.min(min, n), Infinity) : 0;
  const dedented = minIndent ? deGuttered.map((line) => line.slice(minIndent)) : deGuttered;
  const out = [];
  let buffer = [];
  let inCodeBlock = false;
  const flush = () => {
    if (buffer.length) {
      out.push(joinParagraphFragments(buffer));
      buffer = [];
    }
  };
  for (const line of dedented) {
    if (CODE_FENCE_RE.test(line)) {
      flush();
      out.push(line.trimEnd());
      inCodeBlock = !inCodeBlock;
    } else if (inCodeBlock) {
      out.push(line.trimEnd());
    } else if (!line.trim()) {
      flush();
      out.push("");
    } else if (HEADING_RE.test(line) || HR_BANNER_RE.test(line) || BOLD_LABEL_RE.test(line)) {
      flush();
      out.push(line.trimEnd());
    } else if (LIST_ITEM_RE.test(line)) {
      flush();
      buffer.push(line.trimEnd());
    } else if (TABLE_ROW_RE.test(line)) {
      flush();
      out.push(line.trimEnd());
    } else {
      buffer.push(line.trim());
    }
  }
  flush();
  return compressNewlines(out.join("\n"), 2).trim();
};
const splitBySpaces = (input) => {
  if (!input || !input.trim()) return [];
  return input.trim().split(/\s+/).filter((item) => item.length > 0);
};
const applyRemoveCharsToLines = (lines, removeChars) => {
  if (!removeChars.trim()) return lines;
  const chars = splitBySpaces(removeChars);
  return lines.map((line) => {
    let cleaned = line;
    chars.forEach((char) => {
      cleaned = cleaned.replaceAll(char, "");
    });
    return cleaned;
  });
};
const parseEscapeChars = (str) => {
  const map = { n: "\n", r: "\r", t: "	", s: " ", "\\": "\\" };
  return str.replace(/\\([nrts\\])/g, (_, c) => map[c]);
};
const parseSpaceSeparatedItems = (input) => {
  const items = splitBySpaces(input);
  return items.map((item) => parseEscapeChars(item));
};
const escapeRegExp = (str) => str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const convertCase = (text, mode) => {
  switch (mode) {
    case "upper":
      return text.toUpperCase();
    case "lower":
      return text.toLowerCase();
    case "title":
      return text.toLowerCase().replace(/\b\w/g, (c) => c.toUpperCase());
    case "sentence":
      return text.toLowerCase().replace(/(^\s*\w|[.!?]\s+\w)/gm, (c) => c.toUpperCase());
  }
};
const hasPrecisionLossRisk = (input) => {
  var _a;
  const stripped = String(input).replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'/g, '""');
  const runs = stripped.match(/(?<![\w.])\d{16,}(?![\w.])/g);
  return (_a = runs == null ? void 0 : runs.some((run) => String(Number(run)) !== (run.replace(/^0+/, "") || "0"))) != null ? _a : false;
};
export {
  applyRemoveCharsToLines,
  cleanCliText,
  cleanLines,
  compressNewlines,
  convertCase,
  dedupeAdjacentLines,
  dedupeLines,
  escapeRegExp,
  extractPairedLines,
  filterLines,
  hasPrecisionLossRisk,
  isSeparatorBar,
  joinLines,
  normalizeNewlines,
  parseEscapeChars,
  parseSpaceSeparatedItems,
  splitBySpaces,
  splitParagraph,
  splitTextIntoLines,
  toHalfWidth,
  truncate
};
