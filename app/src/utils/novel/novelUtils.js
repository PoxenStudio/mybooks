/* eslint-disable no-useless-escape, no-irregular-whitespace -- 与上游 tools-by-ai 算法逐行一致，正则里的转义/全角空格均为刻意保留 */
import { splitTextIntoLines, compressNewlines, normalizeNewlines, toHalfWidth, cleanLines, filterLines, splitParagraph, dedupeAdjacentLines, isSeparatorBar, escapeRegExp } from "./textUtils";
import { chapterPattern, isChapterTitleLine, detectChapterUnit, pureNumberRegex, novelSectionHeaderRegex, specialLineStartRegex, numberStartRegex, punctuationEndRegex, numberEndRegex, CHAPTER_MARKERS } from "./regex";
const isTitleLine = isChapterTitleLine;
const chapterMarker = (s) => {
  const m = s.match(/第\s*[〇零一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟萬\d]+\s*([章节卷集幕回部篇])/);
  return m ? m[1] : null;
};
const stripOrderPrefix = (s) => s.replace(/^(?:chapter|ch)\.?\s*(?:\d+|[ivxlcdm]+)\s*[.、:：\-]?\s*/i, "").replace(/^\s*(?:\d+|[ivxlcdm]+)\s*[.、．:：\-)\]】]?\s*/i, "").trim().toLowerCase();
const isSameChapter = (a, b) => {
  const ta = a.trim();
  const tb = b.trim();
  if (ta === tb) return true;
  const oa = extractChapterOrder(ta);
  const ob = extractChapterOrder(tb);
  if (oa === null || ob === null || oa !== ob) return false;
  const ma = chapterMarker(ta);
  const mb = chapterMarker(tb);
  if (ma !== mb) return false;
  if (ma !== null) return true;
  return stripOrderPrefix(ta) === stripOrderPrefix(tb);
};
const chineseNumeralToNumber = (input) => {
  var _a;
  const map = {
    零: 0,
    "〇": 0,
    一: 1,
    二: 2,
    两: 2,
    三: 3,
    四: 4,
    五: 5,
    六: 6,
    七: 7,
    八: 8,
    九: 9,
    壹: 1,
    贰: 2,
    叁: 3,
    肆: 4,
    伍: 5,
    陆: 6,
    柒: 7,
    捌: 8,
    玖: 9
  };
  const unit = { 十: 10, 拾: 10, 百: 100, 佰: 100, 千: 1e3, 仟: 1e3 };
  const chars = [...input];
  if (chars.length > 1 && chars.every((ch) => map[ch] !== void 0 || /\d/.test(ch))) {
    let v = 0;
    for (const ch of chars) v = v * 10 + ((_a = map[ch]) != null ? _a : Number(ch));
    return v;
  }
  let total = 0;
  let section = 0;
  let current = 0;
  let has = false;
  for (const ch of input) {
    if (map[ch] !== void 0) {
      current = current + map[ch];
      has = true;
    } else if (unit[ch] !== void 0) {
      if (current === 0) current = 1;
      section += current * unit[ch];
      current = 0;
      has = true;
    } else if (ch === "万" || ch === "萬") {
      section += current;
      if (section === 0) section = 1;
      total += section * 1e4;
      section = 0;
      current = 0;
      has = true;
    } else if (/\d/.test(ch)) {
      current = current * 10 + Number(ch);
      has = true;
    }
  }
  if (!has) return null;
  return total + section + current;
};
const romanToInt = (s) => {
  const map = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1e3 };
  let res = 0;
  let has = false;
  const up = s.toUpperCase();
  for (let i = 0; i < up.length; i++) {
    const val = map[up[i]];
    if (!val) continue;
    has = true;
    const next = i + 1 < up.length ? map[up[i + 1]] || 0 : 0;
    if (val < next) {
      res += next - val;
      i++;
    } else {
      res += val;
    }
  }
  return has ? res : null;
};
const extractChapterOrder = (title) => {
  const m = title.match(/第([〇零一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟萬\d]+)\s*[章节卷集幕回部篇]/);
  if (m) {
    const cn = chineseNumeralToNumber(m[1]);
    if (cn !== null) return cn;
  }
  const en = title.match(/\b(?:chapter|ch)\.?\s*(\d+)\b/i);
  if (en) return parseInt(en[1], 10);
  const roman = title.match(/\b(?:chapter|ch)\.?\s*([ivxlcdm]+)\b/i);
  if (roman) {
    const r = romanToInt(roman[1]);
    if (r !== null) return r;
  }
  if (/^\s*(?:序章|序言|引子|前言|卷首语|扉页|楔子|终章|后记|附录|尾声|番外)/.test(title)) return null;
  const anyNum = title.match(/\d+/);
  if (anyNum) return parseInt(anyNum[0], 10);
  return null;
};
const reorderChaptersByTitle = (text) => {
  var _a;
  const lines = splitTextIntoLines(text || "");
  const unit = detectChapterUnit(lines);
  const chapters = [];
  let current = null;
  const preface = [];
  for (const line of lines) {
    if (isTitleLine(line, unit)) {
      if (current) chapters.push(current);
      const order = (_a = extractChapterOrder(line)) != null ? _a : null;
      current = { title: line, content: [line], order, idx: chapters.length };
    } else {
      if (!current) preface.push(line);
      else current.content.push(line);
    }
  }
  if (current) chapters.push(current);
  if (chapters.length === 0) {
    return { output: text, chapters: 0 };
  }
  const withIndex = chapters.map((c, i) => ({ ...c, i }));
  const firstNumbered = chapters.findIndex((c) => c.order !== null);
  const rank = (c) => c.order !== null ? 1 : firstNumbered === -1 || c.i < firstNumbered ? 0 : 2;
  withIndex.sort((a, b) => {
    const ra = rank(a);
    const rb = rank(b);
    if (ra !== rb) return ra - rb;
    if (ra === 1 && a.order !== b.order) return a.order - b.order;
    return a.i - b.i;
  });
  const parts = [];
  if (preface.length) parts.push(preface.join("\n"));
  for (const ch of withIndex) parts.push(ch.content.join("\n"));
  const out = compressNewlines(parts.join("\n\n"), 2);
  return { output: out, chapters: chapters.length };
};
const splitInlineChapterTitles = (text) => {
  return splitTextIntoLines(text).map((line) => {
    const trimmedLine = line.trim();
    const match = trimmedLine.match(chapterPattern);
    if (match) {
      const chapterTitle = match[1].trim();
      const restContent = match[2].trim();
      if (restContent.includes(")") || restContent.includes("）")) {
        return `${chapterTitle} ${restContent.replace(/[)）]/, "$&\n\n")}`;
      } else {
        const firstSpaceIndex = restContent.indexOf(" ");
        if (firstSpaceIndex !== -1) {
          return `${chapterTitle} ${restContent.substring(0, firstSpaceIndex)}

${restContent.substring(firstSpaceIndex + 1).trim()}`;
        } else if (restContent.length > 30) {
          return `${chapterTitle}

${restContent}`;
        } else {
          return `${chapterTitle} ${restContent}`;
        }
      }
    }
    return line;
  }).join("\n");
};
const removeLineEndNumbers = (text, minLen = 10) => {
  return splitTextIntoLines(text).map((line) => line.length >= minLen ? line.replace(/\d+$/, "") : line).join("\n");
};
const stripNovelArtifacts = (text) => {
  return text.replace(/[\uE000-\uF8FF\uFFFD]/g, " ").replace(/&nbsp;?/g, " ").replace(/Added Url/g, "").replace(/【待续】/g, "");
};
const AD_CUES = [
  /请牢记收藏|记住本站|加入收藏|收藏本页|请大家收藏[：:]/,
  /最快更新请?浏览器|最新最快无防盗|无防盗免费找书/,
  /免费找书|加书可加|找书群\s*[：:]?\d{5,}|本书首发/,
  /关注下方【?\s*QQ ?群|复制下方【?\s*QQ ?群号|复制下面群号|群号加入群聊|一键加群|搜索群号|加全订群|抽奖方式[：:]?\S{0,6}群[（(]?群号[：:]/,
  /(?:中转群|小说群|读书群|交流群|粉丝群|广告群|全订群|订阅群|新群|二群|三群)\s*[：:]?\s*\d{5,}/,
  /联系(?:管理|群管|管理员)?\s*(?:QQ|qq)\s*\d{5,}/,
  /如不慎该资源侵犯了您的权益|侵犯了您的权益|版权归所有|本作品仅供读者|文本仅供|仅供个人学习|请在下载后\d+\s*小时|请观看完毕后删除|24小时[內内]?(?:以)?内[除删]/,
  /每月更新\d+|每日更新\d+|日更\d+\s*[+＋]|全网小说资源|小说源共享|资源每日更新/,
  /从此告别书荒|告[，,]?别书荒/,
  /请购买正版书籍|购买正版谢谢合作|支持订阅正版|感谢对作者的支持|拒绝盗版|如果觉得本书不错/,
  /本书由【[^】]{1,12}】整理/,
  /(?:正在)?转码中|转码中[，,]?请稍后再试/,
  // 网址只吃 URL 安全字符：写成 [^\s，。]{4,} 会把紧跟其后的正文（"https://众人循着方向…"）
  // 一起吞进"广告跨度"，导致后面的判据误判。
  /(?:https?:\/\/|www\.)[A-Za-z0-9._\-\/:?&%#=~+@]{4,}/i,
  /笔趣阁|全文字阅读|txt下载|TXT下载|电子书下载/,
  /资源来自于网络|来自网络，仅作|学习交流使用|学习和试读|更多精彩|请访问|最新章节\W{0,3}请?访问/,
  // 旧 stripNovelArtifacts 里"整块拼齐才命中"的多行水印的残余碎片线索：那几条正则
  // 已删，这些片段必须在这里单独站得住（否则 "本群免费提取全网平台资源" 之类会留下半截）
  /怠惰小说下载器|DownloadAllContent|免费提取全网|全网平台资源|私聊群主|整理[,]?请勿/,
  // 群号行的三种排版：号码在括号内、用破折号引出括号外、或混进混淆字符里
  // 【月漪免费外群1号】——176132292 / 【千寻新免费满文件小说2群：960126270】
  // 【灵梦免费外群6号】——l/-i*/…梦/-首*发830907958
  // 判据取"群"后 30 字内出现 7 位以上连续数字：正文里的电话号码极少与「群」同现，
  // 而作者的打赏鸣谢行（非常感谢【书友160827132928773】的300起点币打赏。）没有「群」，
  // 不该被当成站点广告删掉。
  /群[^\n]{0,30}\d{7,}/,
  // 站方"温馨提醒"话术与引流括号群名
  /合理安排阅读时间|杜绝沉迷网络|尽在【[^】]{0,14}群】/
];
const AD_CUE_SOURCES = AD_CUES.map((re) => `(?:${re.source})`).join("|");
const AD_CUE_UNION = new RegExp(AD_CUE_SOURCES, "i");
const AD_CUE_UNION_G = new RegExp(AD_CUE_SOURCES, "gi");
const AD_SITE_BRANDS = ["刺猬猫", "菠萝包", "飞卢", "飞泸", "点娘", "少年梦", "息壤", "次元姬", "笔趣阁", "纵横", "晋江", "17k", "18k", "起点", "番茄", "七猫", "搜书吧", "sxsy"];
const AD_PREFIX_RESIDUE = /全网|资源|学习|试读|正版|盗版|版权|书荒|转码|防盗|浏览|输入|网址|http|群|收藏|请访问|更多精彩|更新\d/;
const AD_SYMBOL_HEAD = /^[\s=\-—─═_*#~|]{3,}/;
const AD_PROSE_TAIL = /[。！？…”』」]$/;
const adPrefixTrailsInOpenBracket = (s) => {
  const open = Math.max(s.lastIndexOf("【"), s.lastIndexOf("《"), s.lastIndexOf("（"), s.lastIndexOf("("));
  const close = Math.max(s.lastIndexOf("】"), s.lastIndexOf("》"), s.lastIndexOf("）"), s.lastIndexOf(")"));
  return open > close;
};
const AD_MARKETING = /群|收藏|网址|http|www|\.com|\.cn|全网|资源|首发|笔阁|正版|盗版|版权|书荒|转码|更新|下载|访问|试读|牢记|域名|本站/;
const adCjkLen = (s) => (s.match(/[一-鿿぀-ヿ]/g) || []).length;
const adContentLen = (s) => (s.match(/[一-鿿぀-ヿA-Za-z0-9]/g) || []).length;
const adBrandCount = (s) => {
  const low = s.toLowerCase();
  return AD_SITE_BRANDS.reduce((n, b) => n + (low.includes(b.toLowerCase()) ? 1 : 0), 0);
};
const AD_HTML_TAG = /<[^>\n]{1,400}>?/g;
function adInsideHtmlTag(line, at) {
  AD_HTML_TAG.lastIndex = 0;
  let m;
  while ((m = AD_HTML_TAG.exec(line)) !== null) {
    if (m.index <= at && at < m.index + m[0].length) return true;
    if (m.index > at) break;
  }
  return false;
}
const HTML_BLOCK_TAG = /<\/?(?:p|div|br)(?=>|[/\s])[^>\n]{0,120}>/gi;
const HTML_INLINE_TAG = /<\/?(?:font|span|em|strong|small|center|u|i|b)(?=>|[/\s])[^>\n]{0,120}>/gi;
const collapseHtmlLayoutTags = (text) => text.replace(HTML_BLOCK_TAG, "\n\n").replace(HTML_INLINE_TAG, "");
const stripAdLines = (text) => {
  const out = [];
  for (const rawLine of splitTextIntoLines(text)) {
    const line = rawLine.trim();
    if (!line || !AD_CUE_UNION.test(line)) {
      out.push(rawLine);
      continue;
    }
    let cut = -1;
    for (const re of AD_CUES) {
      const m = re.exec(line);
      if (m && m.index >= 0 && (cut === -1 || m.index < cut)) cut = m.index;
    }
    if (cut === -1) {
      if (adBrandCount(line) >= 2 && line.length > 12) continue;
      out.push(rawLine);
      continue;
    }
    if (adInsideHtmlTag(line, cut)) {
      out.push(rawLine);
      continue;
    }
    if (AD_SYMBOL_HEAD.test(line)) continue;
    const prefix = line.slice(0, cut).trim();
    const tail = line.slice(cut);
    const prefixClean = !!prefix && !adPrefixTrailsInOpenBracket(prefix) && !AD_PREFIX_RESIDUE.test(prefix) && adBrandCount(prefix) <= 1;
    if (!prefixClean) continue;
    const tailIsAdRun = tail.length <= 80 && !/[。！？]/.test(tail);
    if (!tailIsAdRun) {
      const residue = line.slice(cut).replace(AD_CUE_UNION_G, " ");
      if (adCjkLen(residue) >= 8 && !AD_MARKETING.test(residue)) out.push(rawLine);
      continue;
    }
    if (adContentLen(prefix) >= 6 || AD_PROSE_TAIL.test(prefix) && adContentLen(prefix) >= 1) out.push(prefix);
  }
  return out.join("\n");
};
const collapseDuplicateChapterTitles = (lines) => {
  const unit = detectChapterUnit(lines);
  const nonEmpty = lines.map((l, i) => ({ l, i })).filter(({ l }) => l.trim());
  const drop = /* @__PURE__ */ new Set();
  const dropRange = (from, to, except) => {
    for (let k = from; k <= to; k++) {
      if (k !== except) drop.add(k);
    }
  };
  let p = 0;
  while (p < nonEmpty.length) {
    if (!isTitleLine(nonEmpty[p].l, unit)) {
      p += 1;
      continue;
    }
    let keepIdx = nonEmpty[p].i;
    let keepText = nonEmpty[p].l;
    let q = p;
    for (; ; ) {
      let nextPos = null;
      if (q + 1 < nonEmpty.length && isTitleLine(nonEmpty[q + 1].l, unit) && isSameChapter(keepText, nonEmpty[q + 1].l)) {
        nextPos = q + 1;
      } else if (q + 2 < nonEmpty.length && !isTitleLine(nonEmpty[q + 1].l, unit) && isTitleLine(nonEmpty[q + 2].l, unit) && isSameChapter(keepText, nonEmpty[q + 2].l)) {
        nextPos = q + 2;
      }
      if (nextPos === null) break;
      const next = nonEmpty[nextPos];
      if (next.l.trim().length > keepText.trim().length) {
        dropRange(keepIdx, next.i, next.i);
        keepIdx = next.i;
        keepText = next.l;
      } else {
        dropRange(keepIdx + 1, next.i, keepIdx);
      }
      q = nextPos;
    }
    p = q + 1;
  }
  return lines.filter((_, i) => !drop.has(i));
};
const formatNovelText = async (text, opts) => {
  let processedInput = normalizeNewlines(text);
  processedInput = stripNovelArtifacts(processedInput);
  processedInput = toHalfWidth(processedInput);
  processedInput = collapseHtmlLayoutTags(processedInput);
  processedInput = stripAdLines(processedInput);
  processedInput = processedInput.replace(new RegExp(`([${CHAPTER_MARKERS}])[、：:]`, "g"), "$1 ").replace(/([\u4e00-\u9fa5]) {2,}([\u4e00-\u9fa5])/g, (match, g1, g2) => {
    return CHAPTER_MARKERS.includes(g1) ? match : g1 + " " + g2;
  });
  if (opts.enableChapterSplit) {
    processedInput = splitInlineChapterTitles(processedInput);
  }
  if (opts.filterText) {
    processedInput = filterLines(processedInput, opts.filterText, { maxLen: opts.maxFilterLineLength });
  }
  if (opts.enableLineEndNumbers) {
    processedInput = removeLineEndNumbers(processedInput, 10);
  }
  if (opts.enableParagraphSplit) {
    processedInput = await splitParagraph(processedInput);
  }
  let lines;
  if (opts.smartLineBreak) {
    lines = cleanLines(processedInput, opts.enableTrim);
  } else {
    lines = splitTextIntoLines(processedInput);
    if (opts.enableTrim) {
      lines = lines.map((line) => line.trim());
    }
  }
  const prepared = opts.mergeDuplicateChapterTitles ? collapseDuplicateChapterTitles(lines) : lines;
  const processedLines = opts.removeDuplicateLines ? dedupeAdjacentLines(prepared) : prepared;
  const chapterUnit = detectChapterUnit(processedLines);
  if (opts.smartLineBreak) {
    const result = [];
    const specialStartRegex = opts.specialStart ? new RegExp(`^${escapeRegExp(opts.specialStart)}`) : null;
    for (let i = 0; i < processedLines.length; i++) {
      const currentLine = processedLines[i];
      if (currentLine.startsWith("分卷阅读") && currentLine.length <= 10) {
        result.push("\n\n");
        continue;
      }
      if (isSeparatorBar(currentLine)) {
        result.push("\n\n");
        continue;
      }
      const previousLine = i > 0 ? processedLines[i - 1].trim() : "";
      const isChapterOrNumber = isTitleLine(currentLine, chapterUnit) || pureNumberRegex.test(currentLine);
      const isSpecialStart = novelSectionHeaderRegex.test(currentLine) || (specialStartRegex == null ? void 0 : specialStartRegex.test(currentLine.trim())) || opts.specialStart && previousLine.startsWith(opts.specialStart);
      const startsWithSpecialChar = specialLineStartRegex.test(currentLine) || numberStartRegex.test(currentLine);
      const prevEndsWithPunctuation = punctuationEndRegex.test(previousLine) || numberEndRegex.test(previousLine) || isSeparatorBar(previousLine);
      if (isChapterOrNumber) {
        result.push("\n\n" + currentLine + (opts.enableIndent ? "\n\n　　" : "\n\n"));
      } else if (isSpecialStart) {
        result.push("\n\n" + currentLine);
      } else if (startsWithSpecialChar || prevEndsWithPunctuation) {
        result.push(opts.enableIndent ? "\n\n　　" + currentLine : "\n\n" + currentLine);
      } else {
        result.push(currentLine);
      }
    }
    processedInput = result.join("");
    processedInput = processedInput.replace(/\n{2,}　　\n{2,}　　/g, "\n\n　　").replace(/\n{2,}　　\n{2,}/g, "\n\n");
    processedInput = compressNewlines(processedInput, 2).trim();
  } else {
    const kept = processedLines.filter((l) => !isSeparatorBar(l));
    processedInput = kept.join("\n");
    processedInput = compressNewlines(processedInput, 1).trim();
  }
  return processedInput;
};
export {
  chineseNumeralToNumber,
  collapseDuplicateChapterTitles,
  collapseHtmlLayoutTags,
  extractChapterOrder,
  formatNovelText,
  removeLineEndNumbers,
  reorderChaptersByTitle,
  romanToInt,
  splitInlineChapterTitles,
  stripAdLines,
  stripNovelArtifacts
};
