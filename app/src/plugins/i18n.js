import Vue from 'vue';
import VueI18n from 'vue-i18n';

Vue.use(VueI18n);

export default ({ app }) => {
  const browserLanguage = navigator.language || navigator.languages[0];
  const defaultLanguage = browserLanguage.startsWith('zh') ? 'zh' : 'en';

  app.i18n = new VueI18n({
    locale: defaultLanguage,
    fallbackLocale: 'zh',
    messages: {
      zh: require('../../locales/zh.json'),
      en: require('../../locales/en.json'),
    },
  });
};
