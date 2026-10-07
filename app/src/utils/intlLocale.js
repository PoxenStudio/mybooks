// Intl.* 需要合法的 BCP-47 语言标签，而 $i18n.locale 可能是站点配置的 'auto'
// （AppHeader 会把 /user/info 的 sys.language 原样写入，'auto' 表示跟随浏览器），
// 把它直接传给 Intl.DateTimeFormat 会抛 RangeError，导致调用它的 computed 渲染失败。
export function intlLocale(i18nLocale) {
    if (i18nLocale && i18nLocale !== 'auto') {
        return i18nLocale;
    }
    if (process.client && navigator.language) {
        return navigator.language;
    }
    return 'zh';
}
