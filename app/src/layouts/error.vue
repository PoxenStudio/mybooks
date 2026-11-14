<template>
  <v-app>
      <div class="error-page">
        <img src="/static/images/error_page.svg" class="error-image" alt="">
        <div class="error-code">
          {{ statusCode }}
        </div>
        <h1 class="error-title">
          {{ message }}
        </h1>
        <v-btn to="/" color="primary" rounded large class="error-btn">
          {{ backHome }}
        </v-btn>
      </div>
  </v-app>
</template>

<script>
export default {
  name: "EmptyLayout",
  layout: "empty",

  props: {
    error: {
      type: Object,
      default: null,
    },
  },
  created() {
    //this.$store.commit("puremode", true);
    // 只有从未保存过外观的用户才按站点默认走；否则会把账号级/本地保存的深浅色顶掉。
    // 走 store 的 mutation（而不是直接改 $vuetify.theme.dark），避免出现第二个真值源。
    if (process.client && !localStorage.getItem("appearance_settings")) {
      this.$store.commit("appearance/adoptSiteTheme", localStorage.getItem("site_theme"));
    }
  },

  computed: {
    statusCode() {
      return (this.error && this.error.statusCode) || 500;
    },
    pageNotFound() {
      return this.$t ? this.$t("error_page_not_found") : "404: 页面已走失，请回首页";
    },
    otherError() {
      return this.$t ? this.$t("error_server_starting") : "[MyBooks] 服务正在启动中，稍后重试";
    },
    message() {
      return this.error && this.error.statusCode === 404 ? this.pageNotFound : this.otherError;
    },
    backHome() {
      return this.$t ? this.$t("common.backToHome") : "返回首页";
    },
  },
  head() {
    return {
      title: this.message,
    };
  },
};
</script>

<style scoped>
.error-page {
  min-height: 30vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  padding-top: 5vh;
  text-align: center;
}

.error-image {
  width: 56px;
  max-width: 40%;
  margin-bottom: 4px;
  opacity: 0.9;
}

/* 状态码用品牌强调色，不再用黄→红渐变：全站唯一一处渐变文字，
   既不用品牌色，也和「红色=删除/错误操作」的语义打架。 */
.error-code {
  font-size: 72px;
  font-weight: 700;
  line-height: 1;
  color: var(--primary-color, #1976D2);
}

.error-divider {
  max-width: 160px;
  margin: 24px 0;
}

.error-title {
  font-size: 20px;
  font-weight: 400;
  margin: 0 0 32px;
  opacity: 0.87;
}

.error-btn {
  min-width: 160px;
  text-transform: none;
}
</style>
