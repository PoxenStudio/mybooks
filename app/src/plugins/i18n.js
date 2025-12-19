import Vue from 'vue';
import VueI18n from 'vue-i18n';

Vue.use(VueI18n);

export default ({ app }) => {
  // 只在客户端环境使用navigator对象
  let defaultLanguage = 'zh';
  if (process.client) {
    const browserLanguage = navigator.language || navigator.languages[0];
    defaultLanguage = browserLanguage.startsWith('zh') ? 'zh' : 'en';
  }

  app.i18n = new VueI18n({
    locale: defaultLanguage,
    fallbackLocale: 'zh',
    messages: {
      zh: require('../../locales/zh.json'),
      en: require('../../locales/en.json'),
    },
  });
};
