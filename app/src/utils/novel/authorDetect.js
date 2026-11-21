/**
 * 从小说正文开头识别作者名（宁缺毋滥）。
 *
 * 只在「文件开头若干行、并且还没进入正文」的范围内找显式声明：
 *   - 作者：XXX / 作者:XXX / 著者：XXX
 *   - XXX 著 / XXX 编著 / XXX 原著
 * 找不到规范写法就返回空串，绝不拿书名、章节标题、正文句子去猜。
 */

const MAX_SCAN_CHARS = 4000;
const MAX_SCAN_LINES = 40;
const MAX_AUTHOR_LEN = 24;

const CN_NUM = "[0-9０-９〇零一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟萬]+";
// 章节/卷首类行：出现即视为正文开始，停止扫描，避免把正文里的「作者：」当成书籍作者
const CHAPTER_LINE = new RegExp(
    `^\\s*(?:第\\s*${CN_NUM}\\s*[章节回卷集部篇幕]|序章|序言|楔子|引子|前言|目录|内容简介|文案|简介)`
);
// 作者名里不该出现的字符（有标点基本就是整句被误抓）
const BAD_AUTHOR_CHARS = /[。，,！？!?；;、<>《》【】()（）"“”'‘’：:/\\|]/;
// 明显不是人名的词
const BAD_AUTHOR_WORDS = /(?:第.{1,6}[章节回卷]|小说|全集|下载|网址|http|www|\.com|\.cn|佚名网|未知)/i;

const AUTHOR_PATTERNS = [
    // 作者：XXX / 著者:XXX / 作家：XXX
    /^\s*(?:作\s*者|著\s*者|作\s*家)\s*[:：]\s*(.+?)\s*$/,
    // XXX 著 / XXX 编著 / XXX 原著（整行只有“名字 + 著作方式”）
    /^\s*(.{1,24}?)\s*(?:编著|原著|著)\s*$/,
];

const WRAPPER_CHARS = new Set(["【", "[", "（", "(", "《", "“", "\"", "'", "】", "]", "）", ")", "》", "”", "’"]);
const stripWrappers = (input) => {
    let start = 0;
    let end = input.length;
    while (start < end && WRAPPER_CHARS.has(input[start])) start += 1;
    while (end > start && WRAPPER_CHARS.has(input[end - 1])) end -= 1;
    return input.slice(start, end);
};

const cleanCandidate = (raw) =>
    stripWrappers(String(raw || ""))
        .replace(/\s*(?:编著|原著|著)\s*$/, "")
        .replace(/^作\s*者\s*[:：]\s*/, "")
        .trim();

const isPlausibleAuthor = (name, title) => {
    if (!name) return false;
    if (name.length < 1 || name.length > MAX_AUTHOR_LEN) return false;
    if (BAD_AUTHOR_CHARS.test(name)) return false;
    if (BAD_AUTHOR_WORDS.test(name)) return false;
    if (new RegExp(`^第\\s*${CN_NUM}\\s*[章节回卷集部篇幕]`).test(name)) return false;
    if (!/[A-Za-z\u4e00-\u9fff]/.test(name)) return false;
    // 书名/作者互相包含，说明抓到的是书名而不是人名（如「作者：乡村乱情」）
    const t = String(title || "").trim();
    if (t) {
        const a = name.replace(/\s+/g, "");
        const b = t.replace(/\s+/g, "");
        if (a && b && (a === b || b.includes(a) || (a.length >= 2 && a.includes(b) && b.length >= 2))) {
            return false;
        }
    }
    return true;
};

export const detectAuthor = (text, title = "") => {
    if (!text) return "";
    const head = text.slice(0, MAX_SCAN_CHARS);
    const lines = head.split(/\r?\n/);

    let scanned = 0;
    for (const line of lines) {
        const value = line.trim();
        if (!value) continue;
        // 进入章节正文就停：作者信息只可能在正文之前
        if (CHAPTER_LINE.test(value)) break;
        scanned += 1;
        if (scanned > MAX_SCAN_LINES) break;
        if (value.length > 60) continue; // 长行是简介/正文，不是署名行

        const cleanedLine = stripWrappers(value);
        for (const pattern of AUTHOR_PATTERNS) {
            const matched = cleanedLine.match(pattern);
            if (!matched) continue;
            const candidate = cleanCandidate(matched[1]);
            if (isPlausibleAuthor(candidate, title)) return candidate;
        }
    }
    return "";
};

export default detectAuthor;
