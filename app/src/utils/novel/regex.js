/* eslint-disable no-useless-escape, no-irregular-whitespace -- 与上游 tools-by-ai 算法逐行一致，正则里的转义/全角空格均为刻意保留 */
const punctuationEndRegex = /(?:[。？！…”"」\]】)）※]|\.{3,}|-{3,}|—{3,}|={3,}|＝{3,})$/;
const specialLineStartRegex = /^(?:[【「\[“"◆※].*|-{3,}|—{3,}|={3,}|＝{3,}|第.*[章节卷])$/;
const pureNumberRegex = /^\d+$/;
const numberStartRegex = /^\d+/;
const numberEndRegex = /\d$/;
const chapterTitleRegex = (
  // 回 的否定预查扩充:回到/回头/回来/回去/回了/回过 等常见句首动词短语在
  // 「数字+回」结构下曾被误判为章节标题(如「三回头看」),导致 reorder 把正文
  // 行当章节移位。
  // 裸标记词(序章/前言/正文/番外…)必须带边界预查:不锚定时任何以这些词
  // 开头的正文句("前言不搭后语"、"正文开始了")都被当标题,reorder 把该句
  // 及其后内容整段搬到文末。允许紧跟:行尾/空白/标点/括号/编号。
  // [上中下][部册]册 → [上中下][部册]:旧写法要求字面 "上部册",真实的
  // 上册/下部 反而永不匹配。
  // 复合形态显式收编:番外篇/正文卷 是起点式 TXT 导出的标准标题前缀
  // ("正文卷 第一章 …"),裸词加边界预查时漏掉它们会让这些标题失识别;
  // 预查类含「第」,容纳 "番外第三章" 直接相连的写法。
  // 「番外之」单列(不走边界预查):番外之一/番外之婚后生活 是晋江/起点的
  // 高频番外标题形态 —— 之 不能进共享预查类(否则 "序章之后，…" 这类散文
  // 也会命中),只对 番外 开例外。
  // [上中下][部册] 的预查窄到 行尾/空白/冒号:真实卷头是 "上册"/"下册 xxx",
  // 共享宽预查会把硬折行首的 "中部，丘陵…"/"上册第3页写道" 误判成标题,
  // reorder 会把其后整块正文搬到文末。
  /^(?:(?:序章|序言|引子|前言|卷首语|扉页|楔子|正文卷?|终章|后记|附录|尾声|番外篇?)(?=$|[\s：:，,、．.·\-—（(【\[「《0-9零一二三四五六七八九十第])|番外之|[上中下][部册](?=$|[\s：:])|第?\s{0,4}[\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+?\s{0,4}(?:章|节(?!课)|卷|集(?![合和])|幕(?![前后布])|回(?![合访忆顾应答音到头来去了过])|部(?![分赛游])|篇(?!张))).*/
);
const CHAPTER_MARKERS = "章节卷集幕回部篇";
const numberTitleRegex = /^[ 　\t]{0,4}\d{1,5}([：:,.， 、_—\-]|【.{1,30}】).{0,30}$/;
const chapterPattern = /^(第?\s{0,4}[\d〇零一二两三四五六七八九十百千万壹贰叁肆伍陆柒捌玖拾佰仟]+?\s{0,4}章)(.*)$/;
const novelSectionHeaderRegex = /^(?:作者|(?:内容|作品)?简介|创作|标签)[:：]?/u;
const CHAPTER_TITLE_MAX_LEN = 40;
const chapterHeadRegex = /^第\s*[〇零一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟萬\d]{1,10}\s*([章节卷集幕回部篇])/;
const sentenceEndRegex = /[。.]$/;
const innerCommaRegex = /[，,]/;
const sectionLabelRegex = /^(?:序章|楔子|正文|终章|末章|后记|後记|尾声|番外|引子|[序前]言|卷首语|扉页|跋)/u;
const detectChapterUnit = (lines) => {
  var _a;
  const tally = /* @__PURE__ */ new Map();
  for (const raw of lines) {
    const t = raw.trim();
    if (!t || [...t].length > CHAPTER_TITLE_MAX_LEN) continue;
    const head = t.match(chapterHeadRegex);
    if (!head) continue;
    if (sentenceEndRegex.test(t) && innerCommaRegex.test(t.slice(0, -1))) continue;
    tally.set(head[1], ((_a = tally.get(head[1])) != null ? _a : 0) + 1);
  }
  let unit = null;
  let max = 0;
  for (const [m, n] of tally) {
    if (n > max) {
      unit = m;
      max = n;
    }
  }
  return unit;
};
const isChapterTitleLine = (line, unit) => {
  const t = line.trim();
  if (!t) return false;
  if ([...t].length > CHAPTER_TITLE_MAX_LEN) return false;
  if (!chapterTitleRegex.test(t) && !numberTitleRegex.test(t)) return false;
  const head = t.match(chapterHeadRegex);
  if (!head && sentenceEndRegex.test(t) && !sectionLabelRegex.test(t)) return false;
  if (head && head[1] !== "章" && sentenceEndRegex.test(t) && innerCommaRegex.test(t.slice(0, -1)) && head[1] !== unit) return false;
  return true;
};
export {
  CHAPTER_MARKERS,
  CHAPTER_TITLE_MAX_LEN,
  chapterPattern,
  chapterTitleRegex,
  detectChapterUnit,
  isChapterTitleLine,
  novelSectionHeaderRegex,
  numberEndRegex,
  numberStartRegex,
  numberTitleRegex,
  punctuationEndRegex,
  pureNumberRegex,
  specialLineStartRegex
};
