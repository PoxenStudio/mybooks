<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('textProcessor.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('textProcessor.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <div class="tp-tool">
      <!-- 顶部工具栏 -->
      <div class="tp-toolbar">
        <button class="tp-btn accent" @click="processText" :title="$t('textProcessor.processBtn')">⚡ {{ $t('textProcessor.processBtn') }}</button>
        <button class="tp-btn" @click="copyHTML" :title="$t('textProcessor.copyHtmlBtn')">📋 {{ $t('textProcessor.copyHtmlBtn') }}</button>
        <button class="tp-btn" @click="copyText" :title="$t('textProcessor.copyTextBtn')">📄 {{ $t('textProcessor.copyTextBtn') }}</button>
        <span class="tp-sep"></span>
        <button class="tp-btn" @click="toggleSettings">⚙️ {{ settingsVisible ? $t('textProcessor.hideSettingsBtn') : $t('textProcessor.settingsBtn') }}</button>
        <button class="tp-btn danger" @click="clearAll">🗑️ {{ $t('textProcessor.clearBtn') }}</button>
      </div>

      <!-- 图书搜索 / 更新栏 -->
      <div class="tp-book-bar">
        <div class="tp-book-search-wrap">
          <input
            type="text"
            class="tp-book-search-input"
            v-model="bookQuery"
            :placeholder="$t('textProcessor.bookSearchPlaceholder')"
            @keyup.enter="searchBook"
          >
          <button class="tp-btn" :disabled="bookSearching" @click="searchBook">🔍 {{ $t('textProcessor.searchBtn') }}</button>
          <div v-if="bookResults.length || (bookSearched && !bookSearching)" class="tp-book-results">
            <div
              v-for="book in bookResults"
              :key="book.id"
              class="tp-book-result-item"
              :class="{ selected: selectedBook && selectedBook.id === book.id }"
              @click="selectBook(book)"
            >
              <v-img class="tp-book-result-cover" :src="book.thumb" :alt="book.title">
                <template #error>
                  <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                </template>
              </v-img>
              <div class="tp-book-result-info">
                <span class="tp-book-result-title">{{ book.title }}</span>
                <span class="tp-book-result-author">{{ (book.authors || []).join(', ') }}</span>
              </div>
            </div>
            <div v-if="bookResults.length === 0" class="tp-book-no-results text-muted">{{ $t('textProcessor.noResults') }}</div>
          </div>
        </div>
        <button class="tp-btn accent" :disabled="!selectedBook || updating" @click="updateBook">
          💾 {{ updating ? $t('textProcessor.updatingBtn') : $t('textProcessor.updateBookBtn') }}
        </button>
      </div>

      <!-- 设置面板 -->
      <div class="tp-settings-panel" :class="{ visible: settingsVisible }">
        <label>
          {{ $t('textProcessor.previewFontSizeLabel') }}
          <input type="range" min="12" max="28" v-model.number="previewFontSize">
          <span>{{ previewFontSize }}px</span>
        </label>
        <label>
          {{ $t('textProcessor.paragraphSpacingLabel') }}
          <input type="range" min="0" max="2" step="0.1" v-model.number="paragraphSpacing">
          <span>{{ paragraphSpacing }}em</span>
        </label>
        <label>
          {{ $t('textProcessor.highlightColorLabel') }}
          <input type="color" v-model="highlightColor">
        </label>
        <span class="tp-sep"></span>
        <div class="tp-rule-group">
          <span class="tp-rule-group-title">{{ $t('textProcessor.keywordRulesLabel') }}</span>
          <div class="tp-rules-list">
            <div v-for="(rule, i) in rules" :key="i" class="tp-rule-item">
              <strong>{{ rule.keyword }}</strong>
              <span class="tp-rule-style">{{ styleLabel(rule.style) }}</span>
              <span class="tp-remove-rule" :title="$t('textProcessor.removeRuleTitle')" @click="removeRule(i)">✕</span>
            </div>
            <span v-if="rules.length === 0" class="text-muted tp-no-rules">{{ $t('textProcessor.noRules') }}</span>
          </div>
          <div class="tp-add-rule-form">
            <input type="text" v-model="newKeyword" :placeholder="$t('textProcessor.keywordPlaceholder')" @keyup.enter="addRule">
            <select v-model="newStyle">
              <option v-for="opt in styleOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <button class="tp-btn-sm" @click="addRule">{{ $t('textProcessor.addRuleBtn') }}</button>
          </div>
        </div>
      </div>

      <!-- 主内容区：左输入 / 右预览 -->
      <div class="tp-main-content">
        <div class="tp-panel">
          <div class="tp-panel-header">
            <span>📥 {{ $t('textProcessor.inputPanelTitle') }}</span>
            <span class="tp-char-count">{{ inputCount }} {{ $t('textProcessor.charsUnit') }}</span>
          </div>
          <div class="tp-panel-body">
            <textarea v-model="inputText" :placeholder="$t('textProcessor.inputPlaceholder')" @input="onInputChange"></textarea>
          </div>
        </div>

        <div class="tp-panel">
          <div class="tp-panel-header">
            <span>👁️ {{ $t('textProcessor.previewPanelTitle') }}</span>
            <span class="tp-char-count">{{ previewCount }} {{ $t('textProcessor.charsUnit') }}</span>
          </div>
          <div class="tp-panel-body">
            <div class="tp-preview-content" ref="previewArea" :style="previewStyle" v-html="previewHtml"></div>
          </div>
        </div>
      </div>

      <!-- 底部 HTML 代码区 -->
      <div class="tp-bottom-panel" :class="{ collapsed: bottomCollapsed }">
        <div class="tp-resize-handle" @mousedown="startResize"></div>
        <div class="tp-panel-header" @click="toggleBottom">
          <span>💻 {{ $t('textProcessor.htmlCodePanelTitle') }}</span>
          <span>{{ bottomCollapsed ? '▶' : '▼' }}</span>
        </div>
        <div class="tp-code-area" ref="codeArea">{{ htmlCode || $t('textProcessor.codePlaceholder') }}</div>
      </div>
    </div>

    <!-- Toast -->
    <div class="tp-toast" :class="{ show: toastVisible }">{{ toastMsg }}</div>
  </v-container>
</template>

<script>
const defaultRules = [
  { keyword: '重要', style: 'bold' },
  { keyword: '注意', style: 'bold-big' },
  { keyword: '警告', style: 'color' },
  { keyword: '提示', style: 'bold' },
  { keyword: '关键', style: 'bold-big' },
];

const RULES_STORAGE_KEY = 'textProcessorRules';

export default {
  data: () => ({
    rules: [],
    settingsVisible: false,

    previewFontSize: 15,
    paragraphSpacing: 0.8,
    highlightColor: '#f9e2af',

    newKeyword: '',
    newStyle: 'bold',

    inputText: '',
    previewHtml: '',
    htmlCode: '',
    inputCount: 0,
    previewCount: 0,

    bottomCollapsed: false,

    bookQuery: '',
    bookResults: [],
    bookSearching: false,
    bookSearched: false,
    selectedBook: null,
    updating: false,

    toastMsg: '',
    toastVisible: false,
    toastTimer: null,
    debounceTimer: null,

    isResizing: false,
    resizeStartY: 0,
    resizeStartHeight: 0,
  }),
  computed: {
    previewStyle() {
      return {
        fontSize: this.previewFontSize + 'px',
        '--tp-paragraph-spacing': this.paragraphSpacing + 'em',
        '--tp-highlight-color': this.highlightColor,
      };
    },
    styleOptions() {
      return [
        { value: 'bold', label: this.$t('textProcessor.styleBold') },
        { value: 'big', label: this.$t('textProcessor.styleBig') },
        { value: 'bold-big', label: this.$t('textProcessor.styleBoldBig') },
        { value: 'color', label: this.$t('textProcessor.styleColor') },
      ];
    },
  },
  created() {
    this.$store.commit('navbar', true);
    this.loadRules();
  },
  mounted() {
    this.inputText = this.$t('textProcessor.sampleText');
    this.inputCount = this.countText(this.inputText);
    this.processText();
  },
  beforeDestroy() {
    clearTimeout(this.debounceTimer);
    clearTimeout(this.toastTimer);
    document.removeEventListener('mousemove', this.onResize);
    document.removeEventListener('mouseup', this.stopResize);
  },
  methods: {
    toggleSettings() {
      this.settingsVisible = !this.settingsVisible;
    },
    styleLabel(style) {
      const opt = this.styleOptions.find(o => o.value === style);
      return opt ? opt.label : style;
    },

    // ==================== 规则管理 ====================
    loadRules() {
      try {
        const saved = localStorage.getItem(RULES_STORAGE_KEY);
        this.rules = saved ? JSON.parse(saved) : [...defaultRules];
      } catch (e) {
        this.rules = [...defaultRules];
      }
    },
    saveRules() {
      localStorage.setItem(RULES_STORAGE_KEY, JSON.stringify(this.rules));
    },
    addRule() {
      const keyword = this.newKeyword.trim();
      const style = this.newStyle;
      if (!keyword) return;
      if (this.rules.some(r => r.keyword === keyword && r.style === style)) {
        this.showToast(this.$t('textProcessor.toastRuleExists'));
        return;
      }
      this.rules.push({ keyword, style });
      this.saveRules();
      this.newKeyword = '';
      this.processText();
      this.showToast(this.$t('textProcessor.toastRuleAdded'));
    },
    removeRule(index) {
      this.rules.splice(index, 1);
      this.saveRules();
      this.processText();
    },

    // ==================== 图书搜索 / 简介更新 ====================
    async searchBook() {
      const q = (this.bookQuery || '').trim();
      if (!q) return;
      this.bookSearching = true;
      this.bookSearched = false;
      this.bookResults = [];
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.bookResults = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (e) {
        this.bookResults = [];
      } finally {
        this.bookSearching = false;
        this.bookSearched = true;
      }
    },
    selectBook(book) {
      this.selectedBook = book;
      this.bookResults = [];
      this.bookSearched = false;
      this.bookQuery = book.title;

      this.inputText = this.stripHtmlToPlainText(book.comments || '');
      this.inputCount = this.countText(this.inputText);
      this.processText();
    },
    stripHtmlToPlainText(html) {
      if (!html) return '';
      if (!/<[a-z][\s\S]*>/i.test(html)) return html;

      let text = html
        .replace(/<\/(p|div|h[1-6]|li|tr|blockquote)>/gi, '\n\n')
        .replace(/<br\s*\/?>/gi, '\n')
        .replace(/<[^>]+>/g, '');

      const div = document.createElement('div');
      div.innerHTML = text;
      text = div.textContent || div.innerText || '';

      return text.replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n').trim();
    },
    async updateBook() {
      if (!this.selectedBook) return;
      this.updating = true;
      try {
        const rsp = await this.$backend(`/book/${this.selectedBook.id}/edit`, {
          method: 'POST',
          body: JSON.stringify({ comments: this.htmlCode }),
        });
        if (rsp.err === 'ok') {
          this.showToast(rsp.msg || this.$t('textProcessor.toastUpdateSuccess'));
        } else {
          this.showToast(rsp.msg || rsp.err);
        }
      } catch (e) {
        this.showToast(String(e));
      } finally {
        this.updating = false;
      }
    },

    // ==================== 文字处理核心 ====================
    escapeHTML(str) {
      const div = document.createElement('div');
      div.appendChild(document.createTextNode(str));
      return div.innerHTML;
    },
    formatBookNames(text) {
      return text.replace(/《([^》]+)》/g, '<b>《$1》</b>');
    },
    applyRules(text) {
      let processed = this.escapeHTML(text);
      const sortedRules = [...this.rules].sort((a, b) => b.keyword.length - a.keyword.length);

      sortedRules.forEach(rule => {
        const escapedKeyword = this.escapeHTML(rule.keyword);
        const regex = new RegExp(escapedKeyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g');

        let replacement;
        switch (rule.style) {
          case 'bold':
            replacement = `<span class="highlight-bold">${escapedKeyword}</span>`;
            break;
          case 'big':
          case 'bold-big':
            replacement = `<h2>${escapedKeyword}</h2>`;
            break;
          case 'color':
            replacement = `<span class="highlight-color">${escapedKeyword}</span>`;
            break;
          default:
            replacement = escapedKeyword;
        }
        processed = processed.replace(regex, replacement);
      });

      return processed;
    },
    countText(str) {
      const chinese = (str.match(/[一-鿿]/g) || []).length;
      const english = (str.match(/[a-zA-Z0-9]+/g) || []).length;
      return chinese + english;
    },
    processText() {
      if (!this.inputText.trim()) {
        this.previewHtml = `<p class="text-muted">${this.$t('textProcessor.emptyInputMsg')}</p>`;
        this.htmlCode = '';
        this.previewCount = 0;
        return;
      }

      const normalized = this.inputText.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
      const paragraphs = normalized.split(/\n{2,}/).filter(p => p.trim() !== '');

      const htmlParts = [];
      paragraphs.forEach(para => {
        const lines = para.trim().split('\n').filter(l => l.trim() !== '');
        if (lines.length === 0) return;

        const escapedLines = lines.map(line => this.formatBookNames(this.applyRules(line)));
        const text = escapedLines.join('<br>');
        htmlParts.push(`<p>${text}</p>`);
      });

      this.htmlCode = htmlParts.join('\n');
      this.previewHtml = htmlParts.join('');

      this.$nextTick(() => {
        const el = this.$refs.previewArea;
        this.previewCount = el ? this.countText(el.innerText || el.textContent || '') : 0;
      });
    },

    // ==================== 输入实时处理（防抖） ====================
    onInputChange() {
      this.inputCount = this.countText(this.inputText);
      clearTimeout(this.debounceTimer);
      this.debounceTimer = setTimeout(this.processText, 300);
    },

    // ==================== 复制功能 ====================
    copyHTML() {
      if (!this.htmlCode.trim()) {
        this.showToast(this.$t('textProcessor.toastNoCopyContent'));
        return;
      }
      navigator.clipboard.writeText(this.htmlCode).then(() => {
        this.showToast(this.$t('textProcessor.toastCopyHtmlSuccess'));
      }).catch(() => {
        this.showToast(this.$t('textProcessor.toastCopyFail'));
      });
    },
    copyText() {
      const el = this.$refs.previewArea;
      const text = el ? (el.innerText || el.textContent || '') : '';
      if (!text.trim()) {
        this.showToast(this.$t('textProcessor.toastNoCopyContent'));
        return;
      }
      navigator.clipboard.writeText(text).then(() => {
        this.showToast(this.$t('textProcessor.toastCopyTextSuccess'));
      }).catch(() => {
        this.showToast(this.$t('textProcessor.toastCopyFail'));
      });
    },
    clearAll() {
      this.inputText = '';
      this.inputCount = 0;
      this.previewHtml = '';
      this.htmlCode = '';
      this.previewCount = 0;
      this.showToast(this.$t('textProcessor.toastCleared'));
    },

    // ==================== Toast ====================
    showToast(msg) {
      this.toastMsg = msg;
      this.toastVisible = true;
      clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => {
        this.toastVisible = false;
      }, 2000);
    },

    // ==================== 底部面板折叠/展开 ====================
    toggleBottom() {
      this.bottomCollapsed = !this.bottomCollapsed;
    },

    // ==================== 底部面板拖拽缩放 ====================
    startResize(e) {
      this.isResizing = true;
      this.resizeStartY = e.clientY;
      this.resizeStartHeight = this.$refs.codeArea.offsetHeight;
      document.body.style.cursor = 'ns-resize';
      document.body.style.userSelect = 'none';

      document.addEventListener('mousemove', this.onResize);
      document.addEventListener('mouseup', this.stopResize);
      e.preventDefault();
    },
    onResize(e) {
      if (!this.isResizing) return;
      const dy = this.resizeStartY - e.clientY;
      const newHeight = Math.max(60, Math.min(500, this.resizeStartHeight + dy));
      this.$refs.codeArea.style.maxHeight = newHeight + 'px';
    },
    stopResize() {
      this.isResizing = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', this.onResize);
      document.removeEventListener('mouseup', this.stopResize);
    },
  },
};
</script>

<style scoped>
.tp-tool {
  --tp-bg: #1e1e2e;
  --tp-surface: #282840;
  --tp-surface2: #313150;
  --tp-border: #3e3e5c;
  --tp-text: #cdd6f4;
  --tp-text-secondary: #a6adc8;
  --tp-accent: #89b4fa;
  --tp-accent2: #a6e3a1;
  --tp-danger: #f38ba8;
  --tp-on-accent: #1e1e2e;
  --tp-code-bg: #181825;
  --tp-placeholder: #585b70;
  --tp-scrollbar-hover: #585b70;
  --tp-radius: 10px;
  --tp-transition: 0.2s ease;

  display: flex;
  flex-direction: column;
  height: 75vh;
  min-height: 560px;
  overflow: hidden;
  border-radius: var(--tp-radius);
  border: 1px solid var(--tp-border);
  background: var(--tp-bg);
  color: var(--tp-text);
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* 顶部工具栏 */
.tp-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: var(--tp-surface);
  border-bottom: 1px solid var(--tp-border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.tp-btn {
  padding: 7px 16px;
  border: 1px solid var(--tp-border);
  border-radius: 6px;
  background: var(--tp-surface2);
  color: var(--tp-text);
  cursor: pointer;
  font-size: 13px;
  transition: all var(--tp-transition);
  white-space: nowrap;
}

.tp-btn:hover {
  background: var(--tp-border);
  border-color: var(--tp-accent);
}

.tp-btn.accent {
  background: var(--tp-accent);
  color: var(--tp-on-accent);
  border-color: var(--tp-accent);
  font-weight: 600;
}

.tp-btn.accent:hover {
  opacity: 0.85;
}

.tp-btn.danger {
  background: transparent;
  border-color: var(--tp-danger);
  color: var(--tp-danger);
}

.tp-btn.danger:hover {
  background: var(--tp-danger);
  color: var(--tp-on-accent);
}

.tp-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.tp-sep {
  width: 1px;
  height: 24px;
  background: var(--tp-border);
  margin: 0 4px;
}

/* 图书搜索 / 更新栏 */
.tp-book-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  background: var(--tp-surface);
  border-bottom: 1px solid var(--tp-border);
  flex-shrink: 0;
  flex-wrap: wrap;
}

.tp-book-search-wrap {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
}

.tp-book-search-input {
  flex: 1;
  padding: 7px 12px;
  background: var(--tp-surface2);
  border: 1px solid var(--tp-border);
  border-radius: 6px;
  color: var(--tp-text);
  font-size: 13px;
  outline: none;
  transition: border-color var(--tp-transition);
}

.tp-book-search-input::placeholder {
  color: var(--tp-placeholder);
}

.tp-book-search-input:focus {
  border-color: var(--tp-accent);
}

.tp-book-results {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  max-height: 240px;
  overflow-y: auto;
  background: var(--tp-surface2);
  border: 1px solid var(--tp-border);
  border-radius: var(--tp-radius);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  z-index: 20;
}

.tp-book-result-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  cursor: pointer;
  border-bottom: 1px solid var(--tp-border);
}

.tp-book-result-item:last-child {
  border-bottom: none;
}

.tp-book-result-item:hover {
  background: var(--tp-border);
}

.tp-book-result-item.selected {
  background: rgba(137, 180, 250, 0.2);
}

.tp-book-result-cover {
  flex: none;
  width: 36px;
  height: 48px;
  border-radius: 4px;
  overflow: hidden;
  background: var(--tp-surface);
}

.tp-book-result-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.tp-book-result-title {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.tp-book-result-author {
  font-size: 11px;
  color: var(--tp-text-secondary);
}

.tp-book-no-results {
  padding: 12px;
  font-size: 12px;
  text-align: center;
}

.tp-selected-book-chip {
  font-size: 12px;
  color: var(--tp-text-secondary);
  background: var(--tp-surface2);
  padding: 6px 12px;
  border-radius: 6px;
  white-space: nowrap;
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 设置面板 */
.tp-settings-panel {
  background: var(--tp-surface);
  border-bottom: 1px solid var(--tp-border);
  padding: 12px 16px;
  display: none;
  flex-shrink: 0;
  flex-wrap: wrap;
  gap: 16px;
  align-items: center;
}

.tp-settings-panel.visible {
  display: flex;
}

.tp-settings-panel label {
  font-size: 13px;
  color: var(--tp-text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.tp-settings-panel input[type="range"] {
  width: 80px;
  accent-color: var(--tp-accent);
}

.tp-settings-panel input[type="color"] {
  width: 32px;
  height: 24px;
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  cursor: pointer;
  background: transparent;
}

.tp-rule-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
}

.tp-rule-group-title {
  font-size: 13px;
  color: var(--tp-text-secondary);
}

.tp-rules-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
}

.tp-rule-item {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--tp-surface2);
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
}

.tp-rule-style {
  color: var(--tp-text-secondary);
}

.tp-remove-rule {
  cursor: pointer;
  color: var(--tp-danger);
  font-weight: bold;
  margin-left: 4px;
}

.tp-remove-rule:hover {
  opacity: 0.8;
}

.tp-no-rules {
  font-size: 12px;
}

.text-muted {
  color: var(--tp-placeholder);
}

.tp-add-rule-form {
  display: flex;
  align-items: center;
  gap: 6px;
}

.tp-add-rule-form input {
  padding: 4px 8px;
  background: var(--tp-surface2);
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  color: var(--tp-text);
  font-size: 12px;
  width: 100px;
}

.tp-add-rule-form select {
  padding: 4px 6px;
  background: var(--tp-surface2);
  border: 1px solid var(--tp-border);
  border-radius: 4px;
  color: var(--tp-text);
  font-size: 12px;
}

.tp-btn-sm {
  padding: 4px 10px;
  font-size: 12px;
  border: 1px solid var(--tp-accent);
  border-radius: 4px;
  background: var(--tp-accent);
  color: var(--tp-on-accent);
  cursor: pointer;
}

/* 主内容区 */
.tp-main-content {
  display: flex;
  flex: 1;
  min-height: 0;
  gap: 1px;
  background: var(--tp-border);
}

.tp-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--tp-surface);
  min-width: 0;
}

.tp-panel-header {
  padding: 8px 14px;
  font-size: 12px;
  font-weight: 600;
  color: var(--tp-text-secondary);
  text-transform: uppercase;
  letter-spacing: 1px;
  border-bottom: 1px solid var(--tp-border);
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tp-char-count {
  font-weight: normal;
  font-size: 11px;
  color: var(--tp-text-secondary);
}

.tp-panel-body {
  flex: 1;
  padding: 16px;
  overflow-y: auto;
  min-height: 0;
}

.tp-panel-body textarea {
  width: 100%;
  height: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  color: var(--tp-text);
  font-size: 15px;
  line-height: 1.8;
  font-family: 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.tp-panel-body textarea::placeholder {
  color: var(--tp-placeholder);
}

.tp-preview-content {
  font-size: 15px;
  line-height: 1.8;
  word-break: break-word;
}

.tp-preview-content >>> p {
  margin-bottom: var(--tp-paragraph-spacing, 0.8em);
}

.tp-preview-content >>> .highlight-bold {
  font-weight: bold;
}

.tp-preview-content >>> h2 {
  font-size: 1.3em;
  font-weight: bold;
  margin: 0.5em 0;
  color: inherit;
  display: block;
}

.tp-preview-content >>> .highlight-color {
  color: var(--tp-highlight-color, #f9e2af);
}

/* 底部 HTML 代码区 */
.tp-bottom-panel {
  flex-shrink: 0;
  background: var(--tp-surface);
  border-top: 1px solid var(--tp-border);
}

.tp-bottom-panel .tp-panel-header {
  cursor: pointer;
  user-select: none;
}

.tp-bottom-panel .tp-panel-header:hover {
  background: var(--tp-surface2);
}

.tp-bottom-panel .tp-code-area {
  padding: 14px 16px;
  background: var(--tp-code-bg);
  max-height: 200px;
  overflow-y: auto;
  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.6;
  color: var(--tp-accent2);
  white-space: pre-wrap;
  word-break: break-all;
}

.tp-bottom-panel.collapsed .tp-code-area {
  display: none;
}

.tp-resize-handle {
  height: 4px;
  background: var(--tp-border);
  cursor: ns-resize;
  transition: background var(--tp-transition);
}

.tp-resize-handle:hover {
  background: var(--tp-accent);
}

/* 滚动条 */
.tp-tool ::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

.tp-tool ::-webkit-scrollbar-track {
  background: transparent;
}

.tp-tool ::-webkit-scrollbar-thumb {
  background: var(--tp-border);
  border-radius: 3px;
}

.tp-tool ::-webkit-scrollbar-thumb:hover {
  background: var(--tp-scrollbar-hover);
}

/* Toast */
.tp-toast {
  position: fixed;
  top: 30%;
  left: 50%;
  transform: translateX(-50%);
  background: var(--tp-accent2);
  color: var(--tp-on-accent);
  padding: 10px 24px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  z-index: 100;
  opacity: 0;
  transition: opacity 0.3s ease;
  pointer-events: none;
}

.tp-toast.show {
  opacity: 1;
}

/* 响应式 */
@media (max-width: 768px) {
  .tp-main-content {
    flex-direction: column;
  }
  .tp-panel {
    flex: none;
    height: 50%;
  }
}
</style>
