<template>
  <v-app dark>
    <v-main>
      <div class="error-page">
        <div class="error-code">
          {{ statusCode }}
        </div>
        <v-divider class="error-divider" />
        <h1 class="error-title">
          {{ message }}
        </h1>
        <v-btn to="/" color="primary" rounded large class="error-btn">
          {{ backHome }}
        </v-btn>
      </div>
    </v-main>
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
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 24px;
  padding-top: 15vh;
  text-align: center;
}

.error-code {
  font-size: 64px;
  font-weight: 700;
  line-height: 1;
  background: linear-gradient(135deg, #4a90d9 0%, #003153 100%);
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
