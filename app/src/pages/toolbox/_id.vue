<template>
  <v-container fluid class="pa-4 toolbox-tool-container">
    <v-row class="mb-3 flex-grow-0" align="center" no-gutters>
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ (tool && tool.name) || $t('toolboxTool.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="goBack">
          <v-icon small left>mdi-close</v-icon>{{ $t('common.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-alert v-if="!tool" type="warning" dense class="mt-2">
      {{ $t('toolboxTool.notFound') }}
    </v-alert>

    <iframe
      v-else
      ref="frame"
      :src="iframeSrc"
      :title="tool.name"
      class="toolbox-tool-frame"
      frameborder="0"
    ></iframe>
  </v-container>
</template>

<script>
// 通用的外部工具承载页：核心 App 只维护这一个构建期就存在的动态路由页面（/toolbox/:id），
// 新增/删除任意数量的外部工具（或被"更新"覆盖过的内置工具）都不需要再改前端代码，见
// document/Toolbox_Dynamic_Design.md 4.1/4.3 节。内置工具各自的静态页面（如
// /toolbox/rare_book_downloader）是构建期就存在的具体路由，Nuxt 按"静态路由优先于动态路由"
// 的规则自动优先匹配，不会落到这个 :id 通配页面上；只有没有对应静态页面的工具（外部工具）
// 才会走到这里。工具自身的 UI 是一个自包含的静态站点，由 <iframe> 加载
// /get/tool/{id}/index.html，与宿主完全隔离（CSS/JS 互不影响）。
export default {
  data: () => ({
    tool: null,
    // 首次渲染时携带一次 theme/locale 作为 iframe 的初始值（4.3 节），此后不再修改
    // src——主题/语言变化改走 postMessage 实时推送（4.5 节），避免每次切换都重新加载 iframe。
    iframeSrc: '',
  }),
  head() {
    return {
      title: (this.tool && this.tool.name) || this.$t('toolboxTool.title'),
    };
  },
  async asyncData({ params, app, res }) {
    if (res !== undefined) {
      res.setHeader('Cache-Control', 'no-cache');
    }
    try {
      const data = await app.$backend('/toolbox/list');
      const tools = (data && data.tools) || [];
      const tool = tools.find((t) => t.id === params.id) || null;
      // status 由后端根据 InstalledTool.enabled 计算，禁用的外部工具在这里也拿不到
      // （见 3.3.1 节），和"根本不存在"是同一种展示——都提示"不存在或已禁用"
      return { tool: tool && tool.status === 'enabled' ? tool : null };
    } catch (e) {
      return { tool: null };
    }
  },
  created() {
    this.$store.commit('navbar', true);
    this.initIframeSrc();
  },
  mounted() {
    window.addEventListener('message', this.onBridgeMessage);
    // 监听宿主语言/主题变化，通过 postMessage 实时推送给 iframe 内的 toolbox-bridge.js
    // （4.5/4.6 节），而不是重设 iframe.src 触发整页重新加载。
    this.unwatchLocale = this.$watch('$i18n.locale', (locale) => {
      this.postToFrame('locale-change', { locale });
    });
    this.unwatchTheme = this.$watch(
      () => this.$vuetify.theme.dark,
      (dark) => {
        this.postToFrame('theme-change', { theme: dark ? 'dark' : 'light' });
      }
    );
  },
  beforeDestroy() {
    window.removeEventListener('message', this.onBridgeMessage);
    if (this.unwatchLocale) this.unwatchLocale();
    if (this.unwatchTheme) this.unwatchTheme();
  },
  methods: {
    goBack() {
      this.$router.push('/admin/toolbox');
    },
    initIframeSrc() {
      if (!this.tool) return;
      const theme = this.$vuetify.theme.dark ? 'dark' : 'light';
      const locale = this.$i18n.locale || 'zh';
      this.iframeSrc = `/get/tool/${this.tool.id}/index.html?theme=${theme}&locale=${encodeURIComponent(locale)}`;
    },
    // 通过 postMessage 通知 iframe 内的 toolbox-bridge.js 主题/语言已变化（4.5 节），
    // 由它自己决定要不要更新、要不要通知工具页面。
    postToFrame(type, payload) {
      const frame = this.$refs.frame;
      if (!frame || !frame.contentWindow) return;
      frame.contentWindow.postMessage(Object.assign({ source: 'mybooks-toolbox-host', type }, payload), window.location.origin);
    },
    // 响应 toolbox-bridge.js 里 bridge.notify() 发出的 postMessage，复用宿主的全局提示组件
    // （见 app/src/plugins/mybooks.js 里的 $alert），4.3 节里描述的可选能力。
    onBridgeMessage(event) {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== 'mybooks-toolbox-bridge' || data.type !== 'notify') return;
      if (this.tool && data.toolId && data.toolId !== this.tool.id) return;
      this.$alert(data.level || 'info', data.message || '');
    },
  },
};
</script>

<style scoped>
.toolbox-tool-container {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 64px);
}
.toolbox-tool-frame {
  flex: 1 1 auto;
  width: 100%;
  border: none;
}
</style>
