<template>
  <v-card outlined class="mb-2">
    <v-card-title
      class="py-1 pr-2 clickable"
      @click="expanded = !expanded"
    >
      <v-icon class="mr-2">mdi-folder-off-outline</v-icon>
      <span class="subtitle-1">{{ $t("settings.scan_ignore_dirs") }}</span>
      <v-chip v-if="names.length" x-small class="ml-2">{{ names.length }}</v-chip>
      <v-spacer></v-spacer>
      <v-btn icon small @click.stop="expanded = !expanded">
        <v-icon>{{
          expanded ? "mdi-chevron-up" : "mdi-chevron-down"
        }}</v-icon>
      </v-btn>
    </v-card-title>
    <v-expand-transition>
      <v-card-text v-show="expanded" class="pt-0">
        <div class="text-caption grey--text mb-3">
          {{ $t("settings.scan_ignore_dirs_hint") }}
        </div>
        <v-row
          v-for="(name, idx) in names"
          :key="idx"
          no-gutters
          align="center"
        >
          <v-col>
            <v-text-field
              :value="name"
              dense
              outlined
              hide-details="auto"
              :placeholder="$t('settings.scan_ignore_dirs_placeholder')"
              :error-messages="errorFor(name)"
              @input="updateAt(idx, $event)"
              @blur="normalizeAt(idx)"
              @keydown.enter.prevent="add"
            ></v-text-field>
          </v-col>
          <v-col cols="auto" class="ml-1">
            <v-btn icon small @click="removeAt(idx)">
              <v-icon small>mdi-delete</v-icon>
            </v-btn>
          </v-col>
        </v-row>
        <v-row>
          <v-col align="center">
            <v-btn text color="primary" small @click="add">
              <v-icon small class="mr-1">mdi-plus</v-icon>
              {{ $t("settings.scan_ignore_dirs_add") }}
            </v-btn>
          </v-col>
        </v-row>
      </v-card-text>
    </v-expand-transition>
  </v-card>
</template>

<script>
// 目录名非法字符：跨平台（含 Windows 客户端同步的场景）统一拒绝路径分隔符、
// 通配符与控制字符；不支持通配符，所以 * 也按非法字符处理。
const INVALID_NAME_CHARS = '/\\:*?"<>|';

export function isInvalidScanIgnoreDirName(name) {
  const value = (name || "").trim();
  if (!value) return false;
  if (value === "." || value === "..") return true;
  for (const ch of value) {
    if (ch.charCodeAt(0) < 32 || INVALID_NAME_CHARS.indexOf(ch) >= 0) {
      return true;
    }
  }
  return false;
}

export default {
  name: "ScanIgnoreDirsEditor",
  props: {
    value: { type: Array, default: () => [] },
  },
  data() {
    return { expanded: false };
  },
  computed: {
    names() {
      return Array.isArray(this.value) ? this.value : [];
    },
  },
  methods: {
    updateAt(idx, val) {
      const next = this.names.slice();
      next[idx] = val;
      this.$emit("input", next);
    },
    normalizeAt(idx) {
      const trimmed = (this.names[idx] || "").trim();
      if (trimmed !== this.names[idx]) this.updateAt(idx, trimmed);
    },
    removeAt(idx) {
      const next = this.names.slice();
      next.splice(idx, 1);
      this.$emit("input", next);
    },
    add() {
      const next = this.names.slice();
      next.push("");
      this.expanded = true;
      this.$emit("input", next);
    },
    errorFor(name) {
      const trimmed = (name || "").trim();
      if (!trimmed) return [];
      if (isInvalidScanIgnoreDirName(trimmed)) {
        return [this.$t("settings.scan_ignore_dirs_invalid")];
      }
      const count = this.names.filter(
        (item) => (item || "").trim() === trimmed
      ).length;
      if (count > 1) {
        return [
          this.$t("settings.scan_ignore_dirs_duplicate", { names: trimmed }),
        ];
      }
      return [];
    },
  },
};
</script>

<style scoped>
.clickable {
  cursor: pointer;
}
</style>
