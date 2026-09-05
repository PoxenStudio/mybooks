<template>
  <v-app>
      <div class="error-page" :style="{ backgroundColor: pageBackground }">
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
    if (process.client) {
      this.$vuetify.theme.dark = localStorage.getItem("site_theme") === "dark";
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
    pageBackground() {
      return this.$vuetify.theme.dark ? "#363636" : "#E7EAE7";
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
  border-radius: 16px !important;
}

.error-image {
  width: 32px;
  max-width: 60%;
  margin-bottom: 10px;
}

.error-code {
  font-size: 80px;
  font-weight: 700;
  line-height: 1;
  background: linear-gradient(135deg, #f6ea0f 0%, #f00404 100%);
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  color: transparent;
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
