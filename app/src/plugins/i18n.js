import Vue from 'vue';
import VueI18n from 'vue-i18n';

Vue.use(VueI18n);

// vue-i18n locale -> Vuetify lang name
const VUETIFY_LOCALE_MAP = { zh: 'zhHans', 'zh-TW': 'zhHant', en: 'en' };

const loadedLocales = [];

// 按需异步加载语言包，webpackChunkName 让三份 locale JSON 各自拆成独立 chunk，
// 而不是像之前那样被 require() 静态打进公共 vendor chunk，三份一起加载。
function loadLocaleMessages(i18n, locale) {
  if (loadedLocales.includes(locale)) {
    return Promise.resolve();
  }
  return import(/* webpackChunkName: "locale-[request]" */ `../../locales/${locale}.json`).then((messages) => {
    i18n.setLocaleMessage(locale, messages.default || messages);
    loadedLocales.push(locale);
  });
}

export default async ({ app }) => {
  // 只在客户端环境使用navigator对象
  let defaultLanguage = 'zh';
  if (process.client) {
    const browserLanguage = navigator.language || navigator.languages[0];
    if (browserLanguage.toLowerCase().replace('_', '-').match(/^zh-(tw|hant|hk|mo)/i)) {
      defaultLanguage = 'zh-TW';
    } else if (browserLanguage.startsWith('zh')) {
      defaultLanguage = 'zh';
    } else {
      defaultLanguage = 'en';
    }
  }

  app.i18n = new VueI18n({
    locale: defaultLanguage,
    fallbackLocale: 'zh',
    messages: {},
  });

  // 首屏只等当前语言加载完成，避免阻塞渲染
  await loadLocaleMessages(app.i18n, defaultLanguage);

  // fallbackLocale('zh') 用于补齐缺失翻译 key，非阻塞地在空闲时预取，
  // 避免非中文用户在个别缺失 key 上看不到回退文案
  if (defaultLanguage !== 'zh') {
    loadLocaleMessages(app.i18n, 'zh');
  }

  if (process.client) {
    window.onNuxtReady((nuxtApp) => {
      const initLocale = VUETIFY_LOCALE_MAP[nuxtApp.$i18n.locale] || 'en';
      nuxtApp.$vuetify.lang.current = initLocale;
      nuxtApp.$watch('$i18n.locale', async (newLocale) => {
        await loadLocaleMessages(nuxtApp.$i18n, newLocale);
        nuxtApp.$vuetify.lang.current = VUETIFY_LOCALE_MAP[newLocale] || 'en';
      });
    });
  }
};
