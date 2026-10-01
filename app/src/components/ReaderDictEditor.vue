<template>
  <div class="pl-6 mt-4">
    <div class="d-flex align-center reader-dict-header" @click="expanded = !expanded">
      <v-icon class="mr-2">mdi-book-alphabet</v-icon>
      <span class="text-body-1">{{ $t("settings.reader_dicts") }}</span>
      <v-icon class="ml-1">{{ expanded ? "mdi-chevron-down" : "mdi-chevron-right" }}</v-icon>
    </div>
    <div class="text-caption grey--text ml-8">{{ $t("settings.reader_dicts_tips") }}</div>
    <v-expand-transition>
    <div v-show="expanded" class="pl-8">
      <v-checkbox
        :input-value="mybooksEnabled"
        :label="$t('settings.reader_dict_mybooks')"
        dense
        hide-details
        @change="$emit('update:mybooksEnabled', !!$event)"
      ></v-checkbox>
      <v-checkbox
        :input-value="baikeEnabled"
        :label="$t('settings.reader_dict_baike')"
        dense
        hide-details
        @change="$emit('update:baikeEnabled', !!$event)"
      ></v-checkbox>
      <v-row
        v-for="(dict, idx) in value"
        :key="'reader-dict-' + dict.id"
        align="center"
        :class="{ 'mt-2': idx === 0 }"
      >
        <v-col class="py-0 pr-0" cols="auto">
          <v-checkbox
            v-model="dict.enabled"
            :title="$t('settings.reader_dict_default_enabled')"
            dense
            hide-details
            class="mt-0"
          ></v-checkbox>
        </v-col>
        <v-col class="py-0">
          <v-text-field
            v-model="dict.name"
            :name="'reader-dict-name-' + dict.id"
            autocomplete="off"
            :label="$t('settings.name')"
            dense
            hide-details
          ></v-text-field>
        </v-col>
        <v-col class="py-2 py-sm-0" cols="12" sm="4">
          <v-text-field
            v-model="dict.url"
            :name="'reader-dict-url-' + dict.id"
            type="url"
            autocomplete="off"
            :label="$t('settings.reader_dict_url')"
            placeholder="https://dict.example.com"
            dense
            hide-details
          >
            <template v-if="tests[dict.id]" v-slot:prepend-inner>
              <v-progress-circular
                v-if="tests[dict.id].status === 'testing'"
                indeterminate
                size="18"
                width="2"
              ></v-progress-circular>
              <v-icon
                v-else
                :color="tests[dict.id].status === 'ok' ? 'success' : 'error'"
                :title="tests[dict.id].msg"
              >{{ tests[dict.id].status === 'ok' ? 'mdi-check-circle' : 'mdi-alert-circle' }}</v-icon>
            </template>
          </v-text-field>
        </v-col>
        <v-col class="py-2 py-sm-0" cols="12" sm="4">
          <v-text-field
            v-model="dict.token"
            :label="$t('settings.reader_dict_token')"
            :type="dict.showToken ? 'text' : 'password'"
            :append-icon="dict.showToken ? 'mdi-eye-off' : 'mdi-eye'"
            append-outer-icon="mdi-delete"
            :name="'reader-dict-token-' + dict.id"
            autocomplete="new-password"
            data-lpignore="true"
            data-1p-ignore
            dense
            hide-details
            @click:append="$set(dict, 'showToken', !dict.showToken)"
            @click:append-outer="removeDict(idx)"
          ></v-text-field>
        </v-col>
      </v-row>
      <v-row>
        <v-col align="center">
          <v-btn color="primary" @click="addDict"
            ><v-icon>mdi-plus</v-icon>{{ $t("settings.add") }}</v-btn
          >
          <v-btn
            color="primary"
            outlined
            class="ml-2"
            :loading="testing"
            :disabled="!testableDicts.length"
            @click="testDicts"
            ><v-icon left>mdi-connection</v-icon>{{ $t("settings.reader_dict_test") }}</v-btn
          >
        </v-col>
      </v-row>
    </div>
    </v-expand-transition>
  </div>
</template>

<script>
// 阅读器站点词典编辑器（MyReader web 版）。
// v-model 绑定 READER_MYDICTS 数组 [{ id, name, url, token, enabled, showToken? }]，
// :mybooks-enabled.sync / :baike-enabled.sync 绑定两个内置词典的默认开关。
export default {
  name: "ReaderDictEditor",
  props: {
    value: { type: Array, required: true },
    mybooksEnabled: { type: Boolean, default: true },
    baikeEnabled: { type: Boolean, default: true },
  },
  data: () => ({
    // Collapsed by default: most sites never need to touch these.
    expanded: false,
    // Per-dictionary result of the last connection test, keyed by dict id.
    tests: {},
    testing: false,
  }),
  computed: {
    testableDicts() {
      return this.value.filter((d) => (d.url || "").trim());
    },
  },
  methods: {
    addDict() {
      // Stable id for the reader's `server:<id>` provider — renaming or
      // re-pointing a dictionary must not look like a new one to readers.
      const id = Math.random().toString(36).slice(2, 10);
      this.$emit("input", [...this.value, { id, name: this.$t("settings.reader_dict_default_name"), url: "", token: "", enabled: true }]);
    },
    removeDict(idx) {
      const list = this.value.slice();
      list.splice(idx, 1);
      this.$emit("input", list);
    },
    async testOne(dict) {
      try {
        const rsp = await this.$backend("/admin/reader/dict/test", {
          method: "POST",
          body: JSON.stringify({ url: dict.url, token: dict.token }),
        });
        if (rsp.err !== "ok") {
          const hints = {
            "dict.not_mydict": "settings.reader_dict_test_not_mydict",
            "dict.unauthorized": "settings.reader_dict_test_unauthorized",
          };
          const detail = hints[rsp.err] ? this.$t(hints[rsp.err], { msg: rsp.msg }) : rsp.msg || rsp.err;
          return { status: "error", msg: this.$t("settings.reader_dict_test_failed", { msg: detail }) };
        }
        const msg = rsp.count === null || rsp.count === undefined
          ? this.$t("settings.reader_dict_test_ok")
          : this.$t("settings.reader_dict_test_ok_count", { word: rsp.word, count: rsp.count });
        return { status: "ok", msg };
      } catch (err) {
        return { status: "error", msg: this.$t("settings.reader_dict_test_failed", { msg: String(err) }) };
      }
    },
    async testDicts() {
      // Tests the addresses/tokens as currently typed, so no save is needed first.
      const dicts = this.testableDicts;
      this.tests = {};
      this.testing = true;
      const results = await Promise.all(
        dicts.map(async (dict) => {
          this.$set(this.tests, dict.id, { status: "testing", msg: "" });
          const result = await this.testOne(dict);
          this.$set(this.tests, dict.id, result);
          return result.status === "ok";
        })
      );
      this.testing = false;
      const ok = results.filter(Boolean).length;
      const failed = results.length - ok;
      this.$alert(failed ? "error" : "success", this.$t("settings.reader_dict_test_summary", { ok, failed }));
    },
  },
};
</script>

<style scoped>
.reader-dict-header {
  cursor: pointer;
  user-select: none;
}
</style>
