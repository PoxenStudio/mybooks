<template>
  <div class="cover-background-manager">
    <p class="text-caption grey--text mb-3">{{ $t("settings.cover_background_hint") }}</p>

    <div class="d-flex align-center flex-wrap mb-3">
      <v-btn small color="primary" :loading="uploading" :disabled="!canUpload" @click="pickFile">
        <v-icon small left>mdi-upload</v-icon>
        {{ $t("settings.cover_background_upload") }}
      </v-btn>
      <input
        ref="fileInput"
        type="file"
        accept="image/jpeg,image/png,image/webp"
        style="display: none"
        @change="onFileChange"
      />
      <span class="ml-3 text-caption grey--text">{{ count }} / {{ max }}</span>
    </div>

    <v-alert v-if="error" type="error" dense text class="mb-3">{{ error }}</v-alert>

    <v-row dense>
      <v-col cols="6" sm="4" md="3" lg="2">
        <v-card outlined>
          <v-img :src="defaultPreviewSrc" aspect-ratio="0.75" @click="openDefaultPreview">
            <template v-slot:placeholder>
              <v-row class="fill-height ma-0" align="center" justify="center">
                <v-progress-circular indeterminate size="20"></v-progress-circular>
              </v-row>
            </template>
          </v-img>
          <div class="text-caption grey--text text-center pt-1">
            {{ $t("settings.cover_background_default") }}
          </div>
          <div class="d-flex align-center justify-space-between">
            <v-checkbox
              dense
              hide-details
              class="mt-0"
              :input-value="defaultSelected"
              :disabled="selecting"
              :label="$t('settings.cover_background_select')"
              @change="toggleDefault"
            ></v-checkbox>
          </div>
        </v-card>
      </v-col>
      <v-col v-for="item in items" :key="item.id" cols="6" sm="4" md="3" lg="2">
        <v-card outlined>
          <v-img :src="item.url" aspect-ratio="0.75" @click="openPreview(item)">
            <template v-slot:placeholder>
              <v-row class="fill-height ma-0" align="center" justify="center">
                <v-progress-circular indeterminate size="20"></v-progress-circular>
              </v-row>
            </template>
          </v-img>
          <div class="d-flex align-center justify-space-between">
            <v-checkbox
              dense
              hide-details
              class="mt-0"
              :input-value="item.selected"
              :disabled="selecting"
              :label="$t('settings.cover_background_select')"
              @change="toggleItem(item, $event)"
            ></v-checkbox>
            <v-btn
              icon
              x-small
              color="error"
              :disabled="selecting"
              @click.stop="askDelete(item)"
            >
              <v-icon small>mdi-delete</v-icon>
            </v-btn>
          </div>
        </v-card>
      </v-col>
    </v-row>
    <p v-if="!items.length" class="text-caption grey--text mt-2">
      {{ $t("settings.cover_background_empty") }}
    </p>

    <v-divider class="my-4"></v-divider>

    <div class="d-flex align-center flex-wrap">
      <v-text-field
        v-model="previewTitle"
        dense
        outlined
        hide-details
        class="mr-3"
        style="max-width: 280px"
        :label="$t('settings.cover_background_preview_title')"
        @keyup.enter="refreshPreview"
      ></v-text-field>
      <v-btn small text color="primary" @click="refreshPreview">
        <v-icon small left>mdi-image-sync-outline</v-icon>
        {{ $t("settings.cover_background_preview") }}
      </v-btn>
    </div>
    <v-img
      v-if="previewSrc"
      :src="previewSrc"
      max-width="240"
      class="mt-2"
      style="border: 1px solid #ddd"
    ></v-img>

    <v-dialog v-model="dialog" max-width="480">
      <v-img v-if="dialogItem" :src="dialogItem.url" contain></v-img>
    </v-dialog>

    <AppDialog
      v-model="deleteDialog"
      type="confirm"
      :title="$t('settings.cover_background_delete')"
      icon="mdi-delete"
      color="error"
      confirm-color="error"
      :max-width="380"
      :dismiss-label="$t('common.cancel')"
      :confirm-text="$t('common.ok')"
      :confirm-loading="deleting"
      @confirm="confirmDelete"
    >
      <p>{{ $t("settings.cover_background_delete_confirm") }}</p>
    </AppDialog>
  </div>
</template>

<script>
const DEFAULT_OPTION = "__default__";

export default {
  name: "cover-background-manager",
  data: () => ({
    items: [],
    count: 0,
    max: 50,
    defaultSelected: true,
    uploading: false,
    deleting: false,
    selecting: false,
    error: "",
    previewTitle: "",
    previewSrc: "",
    dialog: false,
    dialogItem: null,
    deleteDialog: false,
    deleteTarget: null,
  }),
  computed: {
    canUpload() {
      return !this.selecting && !this.uploading && this.count < this.max;
    },
    defaultPreviewSrc() {
      const title = encodeURIComponent(this.$t("settings.cover_background_default"));
      return "/api/cover_backgrounds/preview?library=0&title=" + title;
    },
  },
  mounted() {
    this.load();
  },
  methods: {
    // 增删都返回整份列表，并发请求乱序到达时旧响应会把新状态盖回去；只认最新一次
    _nextSeq() {
      this._reqSeq = (this._reqSeq || 0) + 1;
      return this._reqSeq;
    },
    async load() {
      const seq = this._nextSeq();
      const rsp = await this.$backend("/cover_backgrounds");
      if (seq !== this._reqSeq) return;
      if (rsp.err !== "ok") {
        this.error = rsp.msg || this.$t("message.operationFailed");
        return;
      }
      this.apply(rsp.data);
    },
    apply(data) {
      this.items = (data && data.items) || [];
      this.count = (data && data.count) || 0;
      this.max = (data && data.max) || 50;
      this.defaultSelected = !!(data && data.default_selected);
      this.error = "";
    },
    async setSelected(id, selected) {
      if (this.selecting) return;
      this.selecting = true;
      const item = this.items.find((entry) => entry.id === id);
      const previous = item ? item.selected : this.defaultSelected;
      // Vuetify 2 的 inputValue watcher 只在 prop 变化时回写；先乐观写本地，
      // 失败时 prop 变回旧值才能把勾选框一起拉回去
      if (item) item.selected = selected;
      else this.defaultSelected = selected;
      try {
        const seq = this._nextSeq();
        const rsp = await this.$backend("/cover_backgrounds/select", {
          method: "POST",
          body: new URLSearchParams({ id, selected: selected ? "1" : "0" }),
        });
        if (seq !== this._reqSeq) return;
        if (rsp.err !== "ok") {
          this.error = rsp.msg || this.$t("message.operationFailed");
          if (item) item.selected = previous;
          else this.defaultSelected = previous;
          return;
        }
        this.apply(rsp.data);
        if (this.previewSrc) this.refreshPreview();
      } catch (err) {
        if (item) item.selected = previous;
        else this.defaultSelected = previous;
        this.error = this.$t("message.operationFailed");
      } finally {
        this.selecting = false;
      }
    },
    toggleDefault(value) {
      this.setSelected(DEFAULT_OPTION, value);
    },
    toggleItem(item, value) {
      this.setSelected(item.id, value);
    },
    pickFile() {
      this.$refs.fileInput.click();
    },
    async onFileChange(event) {
      const file = event.target.files[0];
      event.target.value = "";
      if (!file) return;
      if (file.size > 10 * 1024 * 1024) {
        this.error = this.$t("settings.cover_background_too_large");
        return;
      }
      const form = new FormData();
      form.append("file", file);
      const seq = this._nextSeq();
      this.uploading = true;
      try {
        const rsp = await this.$backend("/cover_backgrounds", {
          method: "POST",
          body: form,
        });
        if (seq !== this._reqSeq) return;
        if (rsp.err !== "ok") {
          this.error = rsp.msg || this.$t("message.operationFailed");
          return;
        }
        this.apply(rsp.data);
        this.$alert("success", rsp.msg);
        this.refreshPreview();
      } finally {
        this.uploading = false;
      }
    },
    askDelete(item) {
      this.deleteTarget = item;
      this.deleteDialog = true;
    },
    async confirmDelete() {
      if (!this.deleteTarget) return;
      const seq = this._nextSeq();
      this.deleting = true;
      try {
        const rsp = await this.$backend("/cover_backgrounds/delete", {
          method: "POST",
          body: new URLSearchParams({ id: this.deleteTarget.id }),
        });
        if (seq !== this._reqSeq) return;
        if (rsp.err !== "ok") {
          this.error = rsp.msg || this.$t("message.operationFailed");
          return;
        }
        this.deleteDialog = false;
        this.deleteTarget = null;
        this.apply(rsp.data);
        this.previewSrc = "";
      } finally {
        this.deleting = false;
      }
    },
    openPreview(item) {
      this.dialogItem = item;
      this.dialog = true;
    },
    openDefaultPreview() {
      this.dialogItem = { url: this.defaultPreviewSrc };
      this.dialog = true;
    },
    refreshPreview() {
      const title = encodeURIComponent(this.previewTitle || "");
      this.previewSrc = "/api/cover_backgrounds/preview?t=" + Date.now() + "&title=" + title;
    },
  },
};
</script>
