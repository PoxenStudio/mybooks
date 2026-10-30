<template>
  <div class="homepage-cards-editor pl-6">
    <div class="d-flex align-center mb-2">
      <v-icon small class="mr-2">mdi-view-grid-outline</v-icon>
      <span class="text-body-1">{{ $t("settings.homepage_order_title") }}</span>
    </div>
    <v-list class="homepage-section-list">
      <v-list-item
        v-for="(section, idx) in visibleOrder"
        :key="section"
        class="px-0"
        :class="{ 'homepage-section-drag-over': dragOverSection === section }"
        @dragover.prevent.native="onSectionDragOver(section)"
        @dragleave.native="onSectionDragLeave(section)"
        @drop.prevent.native="onSectionDrop(section)"
      >
        <v-list-item-action class="mr-1">
          <v-icon
            small
            class="homepage-section-handle"
            draggable="true"
            @click.stop
            @dragstart.native="onSectionDragStart(section, $event)"
            @dragend.native="onSectionDragEnd"
          >mdi-drag</v-icon>
        </v-list-item-action>
        <v-list-item-action class="mr-2">
          <v-checkbox
            :input-value="isEnabled(section)"
            hide-details
            dense
            class="mt-0"
            @change="toggleSection(section)"
          ></v-checkbox>
        </v-list-item-action>
        <v-list-item-icon class="mr-2">
          <v-icon small>{{ sectionIcon(section) }}</v-icon>
        </v-list-item-icon>
        <v-list-item-content>
          <v-list-item-title class="text--secondary">{{ sectionTitle(section) }}</v-list-item-title>
        </v-list-item-content>
        <div class="homepage-section-actions">
          <v-btn
            v-if="!isBuiltin(section)"
            icon
            x-small
            color="error"
            class="homepage-section-delete"
            :title="$t('settings.homepage_card_delete')"
            @click.stop="removeCardBySection(section)"
          >
            <v-icon small>mdi-delete-outline</v-icon>
          </v-btn>
          <v-btn icon x-small :disabled="idx === 0" :title="$t('settings.homepage_move_up')" @click="moveSection(section, -1)">
            <v-icon small>mdi-chevron-up</v-icon>
          </v-btn>
          <v-btn icon x-small :disabled="idx === visibleOrder.length - 1" :title="$t('settings.homepage_move_down')" @click="moveSection(section, 1)">
            <v-icon small>mdi-chevron-down</v-icon>
          </v-btn>
        </div>
      </v-list-item>
    </v-list>

    <p class="text-caption grey--text mt-2 mb-0">
      {{ $t("settings.homepage_order_hint") }}
    </p>

    <v-card outlined class="homepage-custom-add mt-6">
      <v-card-text class="pb-3">
        <div class="d-flex align-center mb-3">
          <v-icon small class="mr-2">mdi-plus-circle-outline</v-icon>
          <span class="text-body-2">{{ $t("settings.homepage_add_card") }}</span>
          <v-spacer></v-spacer>
          <v-btn small color="primary" :disabled="!canAdd" @click="addCard">
            <v-icon left small>mdi-plus</v-icon>{{ $t("settings.homepage_add_confirm") }}
          </v-btn>
        </div>
        <v-row dense>
          <v-col cols="12" sm="2">
            <v-select
              v-model="draft.type"
              :items="typeOptions"
              :label="$t('settings.homepage_card_type')"
              dense
              outlined
              hide-details
              @change="onTypeChange"
            ></v-select>
          </v-col>
          <v-col cols="12" sm="4">
            <v-combobox
              v-if="valueFromList"
              v-model="draft.value"
              :items="valueItems"
              :label="$t('settings.homepage_card_value')"
              dense
              outlined
              hide-details
              clearable
              @focus="onValueFocus"
              @update:search-input="onDraftSearch"
            ></v-combobox>
            <v-select
              v-else-if="draft.type === 'language'"
              v-model="draft.value"
              :items="languageItems"
              :label="$t('settings.homepage_card_value')"
              dense
              outlined
              hide-details
            ></v-select>
            <v-select
              v-else
              v-model="draft.value"
              :items="ratingItems"
              :label="$t('settings.homepage_card_value')"
              dense
              outlined
              hide-details
            ></v-select>
          </v-col>
          <v-col cols="6" sm="3">
            <v-select
              v-model="draft.sort"
              :items="sortOptions"
              :label="$t('settings.homepage_card_sort')"
              dense
              outlined
              hide-details
            ></v-select>
          </v-col>
          <v-col cols="6" sm="3">
            <v-select
              v-model="draft.limit"
              :items="limitOptions"
              :label="$t('settings.homepage_card_limit')"
              dense
              outlined
              hide-details
            ></v-select>
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>
  </div>
</template>

<script>
import {
  BUILTIN_SECTIONS,
  CUSTOM_LIMITS,
  CUSTOM_SORTS,
  CUSTOM_TYPES,
  MAX_CUSTOM_CARDS,
  MAX_VALUE_LEN,
  SECTION_META,
  SECTION_MODULE,
  cardSectionKey,
  defaultSortFor,
  normalizeHomepageConfig,
  sectionLabel,
} from "~/utils/homepage";

const TYPE_ICONS = {
  author: "mdi-account-outline",
  tag: "mdi-tag-outline",
  series: "mdi-bookshelf",
  language: "mdi-translate",
  rating: "mdi-star-outline",
};

export default {
  name: "HomepageCardsEditor",
  props: {
    value: {
      type: Object,
      default: null,
    },
    // 功能模块开关快照（sys.modules 或设置页的 moduleState）：模块关闭的卡片
    // 不渲染这一行，但保留在 order 里，保存时不会丢配置
    modules: {
      type: Object,
      default: () => ({}),
    },
  },
  data() {
    return {
      local: normalizeHomepageConfig(this.value),
      emitting: false,
      dragSection: null,
      dragOverSection: null,
      maxCustomCards: MAX_CUSTOM_CARDS,
      // 底部填写区只用于新增，加完即清空
      draft: {
        type: "author",
        value: "",
        sort: "new",
        limit: 12,
      },
      authorItems: [],
      tagItems: [],
      seriesItems: [],
      seriesLoaded: false,
      seriesLoading: false,
      languageItems: [],
      searchTimers: {},
      searchSeq: { author: 0, tag: 0 },
    };
  },
  computed: {
    visibleOrder() {
      return this.local.order.filter((section) => this.moduleOn(SECTION_MODULE[section]));
    },
    canAdd() {
      return this.local.custom.length < this.maxCustomCards && !!String(this.draft.value || "").trim();
    },
    valueFromList() {
      return ["author", "tag", "series"].includes(this.draft.type);
    },
    valueItems() {
      if (this.draft.type === "tag") return this.tagItems;
      if (this.draft.type === "series") return this.seriesItems;
      return this.authorItems;
    },
    typeOptions() {
      return CUSTOM_TYPES.map((type) => ({
        value: type,
        text: this.$t("settings.homepage_type_" + type),
      }));
    },
    sortOptions() {
      return CUSTOM_SORTS.filter((sort) => sort !== "series" || this.draft.type === "series").map((sort) => ({
        value: sort,
        text: this.$t("settings.homepage_sort_" + sort),
      }));
    },
    limitOptions() {
      return CUSTOM_LIMITS.map((value) => ({ value, text: String(value) }));
    },
    ratingItems() {
      return [1, 2, 3, 4, 5].map((value) => ({
        value: String(value),
        text: this.$t("settings.homepage_rating_value", { n: value }),
      }));
    },
  },
  watch: {
    value: {
      deep: true,
      handler(val) {
        if (this.emitting) return;
        const normalized = normalizeHomepageConfig(val);
        if (JSON.stringify(normalized) !== JSON.stringify(this.local)) {
          this.local = normalized;
        }
      },
    },
    local: {
      deep: true,
      handler(val) {
        if (JSON.stringify(val) === JSON.stringify(this.value)) return;
        this.emitting = true;
        this.$emit("input", JSON.parse(JSON.stringify(val)));
        this.$nextTick(() => {
          this.emitting = false;
        });
      },
    },
  },
  mounted() {
    this.loadLanguages();
  },
  beforeDestroy() {
    Object.keys(this.searchTimers).forEach((key) => clearTimeout(this.searchTimers[key]));
  },
  methods: {
    moduleOn(moduleId) {
      if (!moduleId) return true;
      return this.modules[moduleId] !== false;
    },
    isBuiltin(section) {
      return BUILTIN_SECTIONS.includes(section);
    },
    typeIcon(type) {
      return TYPE_ICONS[type] || "mdi-card-outline";
    },
    sectionTitle(section) {
      if (BUILTIN_SECTIONS.includes(section)) {
        const meta = SECTION_META[section];
        return meta ? this.$t(meta.label) : section;
      }
      const card = this.cardForSection(section);
      return card ? sectionLabel(card, (key, params) => this.$t(key, params)) : section;
    },
    sectionIcon(section) {
      if (BUILTIN_SECTIONS.includes(section)) {
        const meta = SECTION_META[section];
        return meta ? meta.icon : "mdi-view-grid-outline";
      }
      const card = this.cardForSection(section);
      return card ? this.typeIcon(card.type) : "mdi-card-outline";
    },
    cardForSection(section) {
      if (!section.startsWith("custom:")) return null;
      const id = section.slice("custom:".length);
      return this.local.custom.find((card) => card.id === id) || null;
    },
    isEnabled(section) {
      return !this.local.hidden.includes(section);
    },
    toggleSection(section) {
      if (this.isEnabled(section)) {
        this.local.hidden = this.local.hidden.concat([section]);
      } else {
        this.local.hidden = this.local.hidden.filter((item) => item !== section);
      }
    },
    moveSection(section, delta) {
      // 按「可见行」相邻关系移动：被模块隐藏的卡片不渲染，但不能因为
      // 找不到相邻项就动不了，也不能把它从 order 里挤掉
      const visible = this.visibleOrder;
      const fromVisible = visible.indexOf(section);
      const toVisible = fromVisible + delta;
      if (fromVisible < 0 || toVisible < 0 || toVisible >= visible.length) return;
      const order = this.local.order.slice();
      const from = order.indexOf(section);
      if (from < 0) return;
      order.splice(from, 1);
      const anchor = visible[toVisible];
      let to = order.indexOf(anchor);
      if (to < 0) return;
      if (delta > 0) to += 1;
      order.splice(to, 0, section);
      this.local.order = order;
    },
    onSectionDragStart(section, event) {
      this.dragSection = section;
      if (event && event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", section);
      }
    },
    onSectionDragOver(section) {
      if (this.dragSection && this.dragSection !== section) {
        this.dragOverSection = section;
      }
    },
    onSectionDragLeave(section) {
      if (this.dragOverSection === section) {
        this.dragOverSection = null;
      }
    },
    onSectionDrop(section) {
      const from = this.local.order.indexOf(this.dragSection);
      const to = this.local.order.indexOf(section);
      if (from === -1 || to === -1 || from === to) {
        this.onSectionDragEnd();
        return;
      }
      const order = this.local.order.slice();
      order.splice(from, 1);
      order.splice(to, 0, this.dragSection);
      this.local.order = order;
      this.onSectionDragEnd();
    },
    onSectionDragEnd() {
      this.dragSection = null;
      this.dragOverSection = null;
    },
    onTypeChange() {
      // 换类型后原来的取值没有意义，排序也回到该类型的默认值
      this.draft.value = "";
      this.draft.sort = defaultSortFor(this.draft.type);
      this.searchSeq.author += 1;
      this.searchSeq.tag += 1;
    },
    onValueFocus() {
      // 丛书下拉一次性拉全量，只有选中「丛书」时才值得发这个请求
      if (this.draft.type === "series") this.loadSeries();
    },
    onDraftSearch(query) {
      this.onValueSearch(this.draft.type, query);
    },
    onValueSearch(type, query) {
      if (type !== "author" && type !== "tag") return;
      if (!query || query.length < 1) return;
      const key = type;
      if (this.searchTimers[key]) clearTimeout(this.searchTimers[key]);
      const seq = this.searchSeq[key] + 1;
      this.searchSeq[key] = seq;
      this.searchTimers[key] = setTimeout(() => {
        const url = key === "author"
          ? "/authors/search?limit=30&q=" + encodeURIComponent(query)
          : "/tags/search?limit=30&q=" + encodeURIComponent(query);
        this.$backend(url).then((rsp) => {
          if (seq !== this.searchSeq[key]) return;
          if (rsp.err !== "ok") return;
          const items = key === "author" ? rsp.authors : rsp.tags;
          const names = (items || []).map((item) => item.name);
          if (key === "author") this.authorItems = names;
          else this.tagItems = names;
        }).catch(() => {
          // 联想输入失败不该弹全局错误，也不是致命问题
        });
      }, 300);
    },
    loadSeries() {
      // 丛书列表可能上千条（/series?show=all 一次返回全部），第一次用到再拉，失败允许重试
      if (this.seriesLoaded || this.seriesLoading) return;
      this.seriesLoading = true;
      this.$backend("/series?show=all").then((rsp) => {
        this.seriesLoading = false;
        if (rsp.err === "ok") {
          this.seriesItems = (rsp.items || []).map((item) => item.name);
          this.seriesLoaded = true;
        }
      }).catch(() => {
        this.seriesLoading = false;
      });
    },
    loadLanguages() {
      this.$backend("/language?show=all").then((rsp) => {
        if (rsp.err === "ok") this.languageItems = (rsp.items || []).map((item) => item.name);
      }).catch(() => {
        // 语言列表拿不到时仍可手填，静默失败
      });
    },
    addCard() {
      if (!this.canAdd) return;
      const id = "c" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      const card = {
        id,
        type: this.draft.type,
        value: String(this.draft.value || "").trim().slice(0, MAX_VALUE_LEN),
        sort: this.draft.sort,
        limit: this.draft.limit,
      };
      this.local.custom = this.local.custom.concat([card]);
      this.local.order = this.local.order.concat([cardSectionKey(card)]);
      // 加完清空内容，保留类型/排序/数量方便连续添加同类卡片
      this.draft = {
        type: card.type,
        value: "",
        sort: card.sort,
        limit: card.limit,
      };
    },
    removeCardBySection(section) {
      const card = this.cardForSection(section);
      if (card) this.removeCard(card);
    },
    removeCard(card) {
      const section = cardSectionKey(card);
      this.local.custom = this.local.custom.filter((item) => item.id !== card.id);
      this.local.order = this.local.order.filter((item) => item !== section);
      this.local.hidden = this.local.hidden.filter((item) => item !== section);
    },
  },
};
</script>

<style scoped>
.homepage-section-list {
  background: transparent;
}

.homepage-section-handle {
  cursor: grab;
}

.homepage-section-handle:active {
  cursor: grabbing;
}

/* 顺序列表右侧操作区：删除（仅自定义卡片）+ 上移/下移，统一排成一行 */
.homepage-section-actions {
  display: flex;
  flex-direction: row;
  align-items: center;
  flex: 0 0 auto;
  margin-left: auto;
  white-space: nowrap;
}

.homepage-section-delete {
  margin-right: 4px;
}

.homepage-section-drag-over {
  outline: 2px dashed #1976d2;
  outline-offset: -2px;
}

.homepage-custom-add {
  border-radius: 8px;
}
</style>
