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

    <v-row v-if="items.length" dense>
      <v-col v-for="item in items" :key="item.id" cols="6" sm="4" md="3" lg="2">
        <v-card outlined>
          <v-img :src="item.url" aspect-ratio="0.75" @click="openPreview(item)">
            <template v-slot:placeholder>
              <v-row class="fill-height ma-0" align="center" justify="center">
                <v-progress-circular indeterminate size="20"></v-progress-circular>
              </v-row>
            </template>
          </v-img>
          <div class="d-flex justify-end">
            <v-btn icon x-small color="error" @click.stop="askDelete(item)">
              <v-icon small>mdi-delete</v-icon>
            </v-btn>
          </div>
        </v-card>
      </v-col>
    </v-row>
    <p v-else class="text-caption grey--text">{{ $t("settings.cover_background_empty") }}</p>

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
        <v-icon small left>mdi-image-refresh</v-icon>
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

    <v-dialog v-model="deleteDialog" max-width="360">
      <v-card>
        <v-card-title class="text-body-1">{{ $t("settings.cover_background_delete") }}</v-card-title>
        <v-card-text>{{ $t("settings.cover_background_delete_confirm") }}</v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn text @click="deleteDialog = false">{{ $t("common.cancel") }}</v-btn>
          <v-btn text color="error" :loading="deleting" @click="confirmDelete">{{ $t("common.ok") }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </div>
</template>

<script>
export default {
  name: "cover-background-manager",
  data: () => ({
    items: [],
    count: 0,
    max: 50,
    uploading: false,
    deleting: false,
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
      return !this.uploading && this.count < this.max;
    },
  },
  mounted() {
    this.load();
  },
  methods: {
    async load() {
      const rsp = await this.$backend("/cover_backgrounds");
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
      this.error = "";
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
      this.uploading = true;
      try {
        const rsp = await this.$backend("/cover_backgrounds", {
          method: "POST",
          body: form,
        });
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
      this.deleting = true;
      try {
        const rsp = await this.$backend("/cover_backgrounds/delete", {
          method: "POST",
          body: new URLSearchParams({ id: this.deleteTarget.id }),
        });
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
    refreshPreview() {
      const title = encodeURIComponent(this.previewTitle || "");
      this.previewSrc = "/api/cover_backgrounds/preview?t=" + Date.now() + "&title=" + title;
    },
  },
};
</script>
