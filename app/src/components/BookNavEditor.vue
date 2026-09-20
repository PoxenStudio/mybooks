<template>
  <div>
    <v-alert v-if="duplicateNames.length" type="error" dense text>
      {{
        $t("settings.book_nav_duplicate_error", {
          names: duplicateNames.join("、"),
        })
      }}
    </v-alert>
    <v-card
      v-for="(cat, idx) in value"
      :key="cat.id"
      outlined
      class="mb-2 book-nav-card"
      :class="{ 'book-nav-card--drag-over': dragOverIdx === idx }"
      @dragover.prevent="onDragOver(idx)"
      @dragleave="onDragLeave(idx)"
      @drop.prevent="onDrop(idx)"
    >
      <v-card-title class="py-1 pr-2">
        <v-icon
          class="book-nav-handle mr-1"
          draggable="true"
          :title="$t('common.dragToReorder')"
          @dragstart="onDragStart(idx, $event)"
          @dragend="onDragEnd"
          >mdi-drag</v-icon
        >
        <v-text-field
          v-model="cat.name"
          solo
          flat
          dense
          hide-details
          class="book-nav-name-field"
          :error="isDuplicate(cat.name)"
          :placeholder="$t('settings.name')"
          @focus="cat.expanded = true"
        ></v-text-field>
        <v-spacer></v-spacer>
        <v-btn icon small @click="removeCategory(idx)">
          <v-icon small>mdi-delete</v-icon>
        </v-btn>
        <v-btn icon @click="cat.expanded = !cat.expanded">
          <v-icon>{{
            cat.expanded ? "mdi-chevron-up" : "mdi-chevron-down"
          }}</v-icon>
        </v-btn>
      </v-card-title>
      <v-expand-transition>
        <v-card-text v-show="cat.expanded" class="pt-0">
          <v-chip
            v-for="(tag, tIdx) in cat.tags"
            :key="tag + '-' + tIdx"
            class="ma-1"
            color="#003153"
            style="color: #fff"
            close
            close-icon="mdi-close"
            @click:close="cat.tags.splice(tIdx, 1)"
          >
            {{ tag }}
          </v-chip>
          <v-chip
            v-if="!cat.addingTag"
            class="ma-1"
            color="#003153"
            style="color: #fff; cursor: pointer"
            @click="startAddTag(cat)"
          >
            <v-icon small color="white">mdi-plus</v-icon>
          </v-chip>
          <v-text-field
            v-else
            v-model="cat.newTag"
            dense
            hide-details
            autofocus
            class="book-nav-tag-input ma-1"
            @keyup.enter="confirmAddTag(cat)"
            @blur="confirmAddTag(cat)"
          ></v-text-field>
        </v-card-text>
      </v-expand-transition>
    </v-card>
    <v-row>
      <v-col align="center">
        <v-btn color="primary" @click="addCategory"
          ><v-icon>mdi-plus</v-icon>{{ $t("settings.add") }}</v-btn
        >
      </v-col>
    </v-row>
  </div>
</template>

<script>
let nextId = 1;

// 书籍分类编辑器。v-model 绑定分类数组 [{ name, tags, expanded, addingTag, newTag }]，
// 数组顺序即保存顺序。列表项使用 createCategory 生成（带稳定 id，保证拖动时 DOM 复用正确）。
export function createCategory(name = "", tags = [], expanded = false) {
  return { id: nextId++, name, tags, expanded, addingTag: false, newTag: "" };
}

export default {
  name: "BookNavEditor",
  props: {
    value: { type: Array, required: true },
  },
  data() {
    return { dragIdx: null, dragOverIdx: null };
  },
  computed: {
    duplicateNames() {
      const counts = {};
      this.value.forEach((cat) => {
        const name = (cat.name || "").trim();
        if (!name) return;
        counts[name] = (counts[name] || 0) + 1;
      });
      return Object.keys(counts).filter((name) => counts[name] > 1);
    },
  },
  methods: {
    isDuplicate(name) {
      const trimmed = (name || "").trim();
      return !!trimmed && this.duplicateNames.includes(trimmed);
    },
    addCategory() {
      this.$emit("input", [...this.value, createCategory("", [], true)]);
    },
    removeCategory(idx) {
      const list = this.value.slice();
      list.splice(idx, 1);
      this.$emit("input", list);
    },
    startAddTag(cat) {
      cat.newTag = "";
      cat.addingTag = true;
    },
    confirmAddTag(cat) {
      const tag = (cat.newTag || "").trim();
      if (tag && !cat.tags.includes(tag)) {
        cat.tags.push(tag);
      }
      cat.newTag = "";
      cat.addingTag = false;
    },
    onDragStart(idx, event) {
      this.dragIdx = idx;
      if (event && event.dataTransfer) {
        event.dataTransfer.effectAllowed = "move";
        event.dataTransfer.setData("text/plain", String(idx));
        // 拖动时显示整张卡片而不是仅图标
        const card = event.target.closest(".book-nav-card");
        if (card) event.dataTransfer.setDragImage(card, 16, 16);
      }
    },
    onDragOver(idx) {
      if (this.dragIdx !== null && this.dragIdx !== idx) {
        this.dragOverIdx = idx;
      }
    },
    onDragLeave(idx) {
      if (this.dragOverIdx === idx) this.dragOverIdx = null;
    },
    onDrop(idx) {
      const from = this.dragIdx;
      if (from !== null && from !== idx) {
        const list = this.value.slice();
        const [moved] = list.splice(from, 1);
        list.splice(idx, 0, moved);
        this.$emit("input", list);
      }
      this.onDragEnd();
    },
    onDragEnd() {
      this.dragIdx = null;
      this.dragOverIdx = null;
    },
  },
};
</script>

<style>
.book-nav-card .book-nav-name-field {
  font-size: 1.1rem;
  font-weight: 500;
}

.book-nav-card .book-nav-name-field .v-input__slot {
  padding: 0 !important;
  box-shadow: none !important;
  background: transparent !important;
}

.book-nav-tag-input {
  display: inline-block;
  width: 120px;
  vertical-align: middle;
}

.book-nav-handle {
  cursor: grab;
}

.book-nav-card--drag-over {
  outline: 2px dashed #1976d2;
  outline-offset: 2px;
}
</style>
