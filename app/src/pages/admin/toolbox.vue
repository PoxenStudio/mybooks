<template>
  <v-container fluid class="pa-4">
    <v-row class="mb-3" align="center">
      <v-col>
        <span class="text-h5 font-weight-bold">{{ $t('toolbox.pageTitle') }}</span>
        <div class="text-caption grey--text mt-1">{{ $t('toolbox.pageSubtitle') }}</div>
      </v-col>
      <v-col cols="auto">
        <v-btn text @click="fetchAll" :loading="loading">
          <v-icon left>mdi-refresh</v-icon>{{ $t('toolbox.refresh') }}
        </v-btn>
        <v-btn v-if="devMode" color="primary" @click="installDialog = true">
          <v-icon left>mdi-upload</v-icon>{{ $t('toolbox.installFromZip') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-alert v-if="error" type="error" dense class="mb-4">{{ error }}</v-alert>

    <v-row v-if="loading" justify="center" class="py-10">
      <v-progress-circular indeterminate color="primary" size="48" />
    </v-row>

    <v-row v-else-if="tools.length === 0" justify="center" class="py-10">
      <v-col cols="auto" class="text-center grey--text">{{ $t('toolbox.noTools') }}</v-col>
    </v-row>

    <v-row v-else>
      <v-col
        v-for="tool in tools"
        :key="tool.id"
        cols="12"
        md="4"
      >
        <v-card
          class="tool-card pa-2 d-flex flex-column"
          rounded="xl"
          outlined
          @click="goToTool(tool)"
          style="cursor: pointer; border: 2px solid #90CAF9; height: 100%;"
        >
          <v-card-text class="d-flex flex-column flex-grow-1">
            <div class="d-flex align-center mb-3">
              <v-avatar size="56" rounded="lg" class="mr-3">
                <v-img
                  :src="`/get/tool/${tool.id}/icon`"
                  :alt="tool.name"
                >
                  <template #error>
                    <v-icon size="36" color="primary">mdi-tools</v-icon>
                  </template>
                </v-img>
              </v-avatar>
              <div class="flex-grow-1">
                <div class="text-subtitle-1 font-weight-bold">{{ tool.name }}</div>
                <div class="d-flex align-center flex-wrap" style="gap: 4px;">
                  <v-chip x-small color="primary" outlined class="mt-1">v{{ tool.revision }}</v-chip>
                  <v-chip x-small outlined class="mt-1">{{ $t(`toolbox.type.${tool.type}`) }}</v-chip>
                  <v-chip v-if="tool.type !== 'builtin'" x-small outlined class="mt-1">{{ $t(`toolbox.source.${tool.source}`) }}</v-chip>
                  <v-chip v-if="tool.status === 'disabled'" x-small color="grey" text-color="white" class="mt-1">
                    {{ $t('toolbox.status.disabled') }}
                  </v-chip>
                  <v-chip v-if="tool.pending_restart" x-small color="warning" text-color="white" class="mt-1">
                    {{ $t('toolbox.pendingRestart') }}
                  </v-chip>
                </div>
              </div>
            </div>
            <div class="tool-desc text-body-2 grey--text text--darken-1 mb-3">
              {{ tool.description }}
            </div>
            <div class="d-flex justify-space-between align-center text-caption grey--text mt-auto mb-2">
              <span><v-icon x-small>mdi-account-outline</v-icon> {{ tool.author }}</span>
              <span v-if="tool.publish_date"><v-icon x-small>mdi-calendar-outline</v-icon> {{ tool.publish_date }}</span>
            </div>

            <v-divider class="mb-2" />
            <div class="d-flex align-center" style="gap: 4px;" @click.stop>
              <v-switch
                v-if="tool.type === 'tool'"
                :input-value="tool.status === 'enabled'"
                dense
                hide-details
                :loading="busyToolId === tool.id"
                :disabled="busyToolId === tool.id"
                @change="toggleEnabled(tool)"
                class="mt-0 pt-0"
              ></v-switch>
              <v-spacer></v-spacer>
              <v-btn v-if="devMode && tool.source === 'dev'" x-small text @click="openUpdateDialog(tool)">
                <v-icon x-small left>mdi-file-upload-outline</v-icon>{{ $t('toolbox.update') }}
              </v-btn>
              <v-btn
                v-if="tool.type === 'tool'"
                x-small
                text
                color="error"
                :loading="busyToolId === tool.id"
                :disabled="busyToolId === tool.id"
                @click="confirmUninstall(tool)"
              >
                <v-icon x-small left>mdi-delete-outline</v-icon>{{ $t('toolbox.uninstall') }}
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 工具商店：ENABLE_TOOLBOX_STORE=False 时列表恒为空，展示"暂无可安装工具" -->
    <v-row class="mt-6 mb-2" align="center" hidden>
      <v-col>
        <span class="text-h6 font-weight-bold">{{ $t('toolbox.storeTitle') }}</span>
        <div class="text-caption grey--text mt-1">{{ $t('toolbox.storeSubtitle') }}</div>
      </v-col>
    </v-row>
    <v-row v-if="storeTools.length === 0" justify="center" class="py-6">
      <v-col cols="auto" class="text-center grey--text">{{ $t('toolbox.storeEmpty') }}</v-col>
    </v-row>
    <v-row v-else>
      <v-col v-for="entry in storeTools" :key="entry.tool_id" cols="12" md="4">
        <v-card class="pa-2" rounded="xl" outlined>
          <v-card-text>
            <div class="text-subtitle-1 font-weight-bold">{{ entry.name }}</div>
            <div class="text-body-2 grey--text text--darken-1 mb-2">{{ entry.description }}</div>
            <div class="d-flex align-center justify-space-between">
              <v-chip x-small outlined>v{{ entry.latest_revision }}</v-chip>
              <v-btn
                x-small
                color="primary"
                :loading="busyToolId === entry.tool_id"
                :disabled="busyToolId === entry.tool_id || (entry.installed && entry.installed_revision === entry.latest_revision)"
                @click="installFromStore(entry)"
              >
                {{ entry.installed ? $t('toolbox.storeUpdate') : $t('toolbox.storeInstall') }}
              </v-btn>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <!-- 本地上传安装（开发者模式） -->
    <AppDialog
      v-model="installDialog"
      :persistent="false"
      type="action"
      :title="$t('toolbox.installFromZip')"
      max-width="480"
      :dismiss-label="$t('toolbox.cancel')"
      :confirm-text="$t('toolbox.install')"
      :confirm-loading="installing"
      :confirm-disabled="!installFile"
      @confirm="submitInstall"
    >
      <v-file-input
        v-model="installFile"
        accept=".zip"
        :label="$t('toolbox.selectZip')"
        show-size
      ></v-file-input>
    </AppDialog>

    <!-- 本地上传更新（开发者模式，builtin/tool 均可） -->
    <AppDialog
      v-model="updateDialog"
      :persistent="false"
      type="action"
      :title="$t('toolbox.updateTool', { name: updateTarget && updateTarget.name })"
      max-width="480"
      :dismiss-label="$t('toolbox.cancel')"
      :confirm-text="$t('toolbox.update')"
      :confirm-loading="updating"
      :confirm-disabled="!updateFile"
      @confirm="submitUpdate"
    >
      <v-file-input
        v-model="updateFile"
        accept=".zip"
        :label="$t('toolbox.selectZip')"
        show-size
      ></v-file-input>
    </AppDialog>

    <!-- 卸载确认 -->
    <AppDialog
      v-model="uninstallDialog"
      :persistent="false"
      type="confirm"
      :title="$t('toolbox.uninstall')"
      color="deep-orange"
      confirm-dark
      max-width="420"
      :dismiss-label="$t('toolbox.cancel')"
      :confirm-text="$t('toolbox.uninstall')"
      @confirm="doUninstall"
    >
      {{ $t('toolbox.uninstallConfirm', { name: uninstallTarget && uninstallTarget.name }) }}
    </AppDialog>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    tools: [],
    loading: false,
    error: null,
    devMode: false,
    storeEnabled: false,
    storeTools: [],
    busyToolId: null,
    installDialog: false,
    installFile: null,
    installing: false,
    updateDialog: false,
    updateTarget: null,
    updateFile: null,
    updating: false,
    uninstallDialog: false,
    uninstallTarget: null,
  }),
  head() {
    return { title: this.$t('toolbox.pageTitle') };
  },
  async asyncData({ app, res }) {
    if (res !== undefined) {
      res.setHeader("Cache-Control", "no-cache");
    }
    try {
      const [listRsp, storeRsp] = await Promise.all([
        app.$backend("/toolbox/list?include_disabled=1"),
        app.$backend("/toolbox/store/index"),
      ]);
      if (listRsp.err !== "ok") {
        return { tools: [], error: listRsp.msg || "error" };
      }
      return {
        tools: listRsp.tools || [],
        devMode: !!listRsp.dev_mode,
        storeEnabled: !!listRsp.store_enabled,
        storeTools: (storeRsp && storeRsp.err === "ok" && storeRsp.tools) || [],
      };
    } catch (e) {
      return { tools: [], error: String(e) };
    }
  },
  created() {
    this.$store.commit("navbar", true);
  },
  methods: {
    goToTool(tool) {
      const toolPage = tool.page || tool.id;
      // 统一走 /toolbox/{page}：内置工具（source==='bundled'）有自己构建期就存在的静态页面，
      // Nuxt 按"静态路由优先于动态路由"自动匹配到它；没有静态页面的工具（外部工具，或被
      // "更新"覆盖过的内置工具）会落到通用承载页 /toolbox/_id.vue，用 <iframe> 加载，
      // 见 document/Toolbox_Dynamic_Design.md 4.3 节。
      this.$router.push(`/toolbox/${toolPage}`);
    },
    async fetchAll() {
      this.loading = true;
      this.error = null;
      try {
        const [listRsp, storeRsp] = await Promise.all([
          this.$backend("/toolbox/list?include_disabled=1"),
          this.$backend("/toolbox/store/index"),
        ]);
        if (listRsp.err !== "ok") {
          this.error = listRsp.msg || listRsp.err;
          return;
        }
        this.tools = listRsp.tools || [];
        this.devMode = !!listRsp.dev_mode;
        this.storeEnabled = !!listRsp.store_enabled;
        this.storeTools = (storeRsp && storeRsp.err === "ok" && storeRsp.tools) || [];
      } catch (e) {
        this.error = String(e);
      } finally {
        this.loading = false;
      }
    },
    async toggleEnabled(tool) {
      this.busyToolId = tool.id;
      const action = tool.status === 'enabled' ? 'disable' : 'enable';
      try {
        const rsp = await this.$backend(`/toolbox/${tool.id}/${action}`, { method: 'POST' });
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg || rsp.err);
          return;
        }
        this.$alert('success', rsp.msg);
        await this.fetchAll();
      } catch (e) {
        this.$alert('error', String(e));
      } finally {
        this.busyToolId = null;
      }
    },
    confirmUninstall(tool) {
      this.uninstallTarget = tool;
      this.uninstallDialog = true;
    },
    async doUninstall() {
      const tool = this.uninstallTarget;
      this.uninstallDialog = false;
      if (!tool) return;
      this.busyToolId = tool.id;
      try {
        const rsp = await this.$backend(`/toolbox/${tool.id}`, { method: 'DELETE' });
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg || rsp.err);
          return;
        }
        this.$alert('success', rsp.msg);
        await this.fetchAll();
      } catch (e) {
        this.$alert('error', String(e));
      } finally {
        this.busyToolId = null;
      }
    },
    async submitInstall() {
      if (!this.installFile) return;
      this.installing = true;
      try {
        const formData = new FormData();
        formData.append('file', this.installFile);
        const response = await fetch('/api/toolbox/install/upload', { method: 'POST', body: formData });
        const rsp = await response.json();
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg || rsp.err);
          return;
        }
        this.$alert('success', rsp.msg);
        this.installDialog = false;
        this.installFile = null;
        await this.fetchAll();
      } catch (e) {
        this.$alert('error', String(e));
      } finally {
        this.installing = false;
      }
    },
    openUpdateDialog(tool) {
      this.updateTarget = tool;
      this.updateFile = null;
      this.updateDialog = true;
    },
    async submitUpdate() {
      if (!this.updateFile || !this.updateTarget) return;
      this.updating = true;
      try {
        const formData = new FormData();
        formData.append('file', this.updateFile);
        const response = await fetch(`/api/toolbox/${this.updateTarget.id}/update/upload`, { method: 'POST', body: formData });
        const rsp = await response.json();
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg || rsp.err);
          return;
        }
        this.$alert('success', rsp.msg);
        this.updateDialog = false;
        this.updateFile = null;
        await this.fetchAll();
      } catch (e) {
        this.$alert('error', String(e));
      } finally {
        this.updating = false;
      }
    },
    async installFromStore(entry) {
      this.busyToolId = entry.tool_id;
      try {
        const rsp = await this.$backend(`/toolbox/${entry.tool_id}/install`, { method: 'POST' });
        if (rsp.err !== 'ok') {
          this.$alert('error', rsp.msg || rsp.err);
          return;
        }
        this.$alert('success', rsp.msg);
        await this.fetchAll();
      } catch (e) {
        this.$alert('error', String(e));
      } finally {
        this.busyToolId = null;
      }
    },
  },
};
</script>

<style scoped>
.tool-card {
  transition: box-shadow 0.2s, transform 0.2s;
}
.tool-card:hover {
  box-shadow: 0 6px 20px rgba(144, 202, 249, 0.45) !important;
  transform: translateY(-2px);
}
/* 简介固定为 3 行高度：文字不足时占位保持一致，超出时省略号截断 */
.tool-desc {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: calc(1.5em * 3);
  line-height: 1.5em;
}
</style>
