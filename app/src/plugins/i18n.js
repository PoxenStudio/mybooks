import Vue from 'vue';
import VueI18n from 'vue-i18n';

Vue.use(VueI18n);

// vue-i18n locale -> Vuetify lang name
const VUETIFY_LOCALE_MAP = { zh: 'zhHans', 'zh-TW': 'zhHant', en: 'en' };

export default ({ app }) => {
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
    messages: {
      zh: require('../../locales/zh.json'),
      'zh-TW': require('../../locales/zh-TW.json'),
      en: require('../../locales/en.json'),
    },
  });

  if (process.client) {
    window.onNuxtReady((nuxtApp) => {
      const initLocale = VUETIFY_LOCALE_MAP[nuxtApp.$i18n.locale] || 'en';
      nuxtApp.$vuetify.lang.current = initLocale;
      nuxtApp.$watch('$i18n.locale', (newLocale) => {
        nuxtApp.$vuetify.lang.current = VUETIFY_LOCALE_MAP[newLocale] || 'en';
      });
    });
  }
};
