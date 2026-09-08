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
      :style="{ height: iframeHeight }"
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
    // toolbox-bridge.js 会自动上报工具页面的实际内容高度（resize 消息，见 onBridgeMessage）；
    // 撑满可视区这个初始值只是首次渲染、还没收到第一条上报之前的占位，避免那零点几秒里
    // iframe 塌成一条缝。之后随内容高度增长，交给宿主页面自己的滚动条，不再让工具页面在
    // 自己的 iframe 里出现内部滚动条。
    iframeHeight: 'calc(100vh - 64px)',
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
    // 响应 toolbox-bridge.js 发来的 postMessage：notify 复用宿主的全局提示组件（见
    // app/src/plugins/mybooks.js 里的 $alert，4.3 节里描述的可选能力）；resize 是
    // bridge.js 自动上报的工具页面实际内容高度，用来把 iframe 撑到刚好装下内容，而不是
    // 固定卡在 calc(100vh - 64px) 里逼工具页面自己出内部滚动条。
    onBridgeMessage(event) {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.source !== 'mybooks-toolbox-bridge') return;
      if (this.tool && data.toolId && data.toolId !== this.tool.id) return;
      if (data.type === 'notify') {
        this.$alert(data.level || 'info', data.message || '');
      } else if (data.type === 'resize' && typeof data.height === 'number' && data.height > 0) {
        // 给个下限：内容比视口矮的工具页面依然撑满可视区，不会因为"自动贴合内容"反而缩成
        // 一小条，视觉上和之前保持一致；只有内容更高时才让 iframe（进而是宿主页面）变高。
        const minHeight = window.innerHeight - 64;
        this.iframeHeight = Math.max(data.height, minHeight) + 'px';
      }
    },
  },
};
</script>

<style scoped>
.toolbox-tool-container {
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 64px);
}
.toolbox-tool-frame {
  width: 100%;
  border: none;
  transition: height 0.15s ease;
}
</style>
