<template>
  <header class="wap-header">
    <div class="wap-header-left">
      <template v-if="isLoggedIn">
        <img :src="user.avatar" class="user-avatar" alt="avatar" />
      </template>
      <template v-else>
        <button class="login-btn" @click="handleLogin">登录</button>
      </template>
    </div>
    <div class="wap-header-center">
      <a href="/wap" class="site-name">Talebook</a>
    </div>
    <div class="wap-header-right">
      <template v-if="isLoggedIn">
        <button class="logout-btn" @click="handleLogout">退出</button>
      </template>
    </div>
  </header>
</template>

<script>
export default {
  name: 'WapHeader',
  data() {
    return {
    };
  },
  computed: {
    isLoggedIn() {
      return this.$store.state.user && this.$store.state.user.is_login;
    },
    user() {
      return this.$store.state.user || {};
    },
  },
  methods: {
    handleLogin() {
      this.$router.push('/wap/login');
    },
    handleLogout() {
      this.$backend('/user/sign_out').then( rsp => {
        if (rsp.err === 'ok') {
          this.$store.commit('logout');
          this.$store.state.user.is_login = false;
          this.$store.state.user = null;
        }
        this.$router.push('/wap');
      });
    }
  }
};
</script>

<style scoped>
.wap-header {
  border-bottom: 1px solid #ccc;
  padding: 8px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.wap-header-left {
  display: flex;
  align-items: center;
  flex: 1;
}
.wap-header-center {
  flex: 1;
  text-align: center;
}
.wap-header-right {
  display: flex;
  align-items: center;
  flex: 1;
  justify-content: flex-end;
}
.login-btn, .logout-btn {
  padding: 4px 12px;
  border: 1px solid #ccc;
  background: #f5f5f5;
  cursor: pointer;
  border-radius: 4px;
}
.site-name {
  font-weight: bold;
  font-size: 24px;
  text-decoration: none;
  color: #333;
}
.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  cursor: pointer;
  background-color: #003153;
}
</style>
