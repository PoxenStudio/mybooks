<template>
  <v-container fluid class="pa-4">
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('mimoTts.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('mimoTts.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="mt-card pa-6">
          <v-alert type="warning" dense text rounded="lg" class="mb-5">
            {{ $t('mimoTts.hint') }}
          </v-alert>

          <v-text-field
            v-model="query"
            :label="$t('mimoTts.selectBook')"
            :loading="searching"
            outlined
            dense
            clearable
            hide-details
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="search"
            @click:clear="clearSearch"
          />

          <div class="mt-book-list mb-4">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('mimoTts.noResults', $t('epubSplit.noResults')) }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="mt-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['mt-book-item', { 'mt-book-selected': selected && selected.id === book.id }]"
                @click="selectBook(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="mt-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="mt-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      :color="file.format === 'EPUB' ? 'primary' : 'default'"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="selected && selected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>

          <template v-if="selected">
            <v-divider class="mb-4" />

            <!-- API type selector -->
            <v-select
              v-model="apiType"
              :label="$t('mimoTts.apiType')"
              :items="apiTypeOptions"
              item-title="label"
              item-value="value"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-api"
              @update:model-value="onApiTypeChange"
            />

            <!-- API URL -->
            <v-text-field
              v-model="apiUrl"
              :label="$t('mimoTts.apiUrl')"
              :placeholder="$t('mimoTts.apiUrlPlaceholder')"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-link-variant"
            />

            <!-- Model name -->
            <v-text-field
              v-model="modelName"
              :label="$t('mimoTts.modelName')"
              :placeholder="$t('mimoTts.modelNamePlaceholder')"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-chip"
            />

            <!-- Auth type -->
            <v-select
              v-model="authType"
              :label="$t('mimoTts.authType')"
              :items="authTypeOptions"
              item-title="label"
              item-value="value"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-shield-key"
            />

            <!-- API Key -->
            <v-text-field
              v-model="apiKey"
              :label="$t('mimoTts.apiKey')"
              :placeholder="$t('mimoTts.apiKeyPlaceholder')"
              outlined
              dense
              hide-details
              class="mb-4"
              prepend-inner-icon="mdi-key-variant"
              type="password"
            />

            <!-- Voice: chat_completions mode -->
            <template v-if="apiType === 'chat_completions'">
              <v-select
                v-model="voiceType"
                :label="$t('mimoTts.voiceLabel')"
                :items="voiceOptions"
                item-title="label"
                item-value="value"
                outlined
                dense
                hide-details
                class="mb-3"
                prepend-inner-icon="mdi-account-voice"
              />
              <v-textarea
                v-if="voiceType === 'custom'"
                v-model="customVoice"
                :label="$t('mimoTts.voiceCustom')"
                :placeholder="$t('mimoTts.voiceCustomPlaceholder')"
                outlined
                dense
                hide-details
                auto-grow
                rows="2"
                class="mb-4"
              />
            </template>

            <!-- Voice: audio_speech mode -->
            <template v-else-if="apiType === 'audio_speech'">
              <v-select
                v-model="voiceName"
                :label="$t('mimoTts.voiceName')"
                :items="speechVoiceOptions"
                item-title="label"
                item-value="value"
                outlined
                dense
                hide-details
                class="mb-4"
                prepend-inner-icon="mdi-account-voice"
              />
            </template>

            <!-- Voice: custom mode (same as chat) -->
            <template v-else>
              <v-select
                v-model="voiceType"
                :label="$t('mimoTts.voiceLabel')"
                :items="voiceOptions"
                item-title="label"
                item-value="value"
                outlined
                dense
                hide-details
                class="mb-3"
                prepend-inner-icon="mdi-account-voice"
              />
              <v-textarea
                v-if="voiceType === 'custom'"
                v-model="customVoice"
                :label="$t('mimoTts.voiceCustom')"
                :placeholder="$t('mimoTts.voiceCustomPlaceholder')"
                outlined
                dense
                hide-details
                auto-grow
                rows="2"
                class="mb-4"
              />
            </template>

            <transition name="mt-fade">
              <v-alert
                v-if="resultMsg"
                :type="resultType"
                dense
                text
                rounded="lg"
                class="mb-4"
              >{{ resultMsg }}</v-alert>
            </transition>

            <div class="d-flex justify-center">
              <v-btn
                color="primary"
                class="mt-start-btn"
                :loading="processing"
                :disabled="processing || !canConvert"
                @click="startConvert"
              >
                <v-icon left>mdi-voice</v-icon>
                {{ $t('mimoTts.startBtn') }}
              </v-btn>
            </div>

            <div v-if="completed" class="d-flex justify-center mt-4">
              <v-btn
                color="success"
                outlined
                @click="$router.push('/audio/' + selected.id)"
              >
                <v-icon left>mdi-headphones</v-icon>
                {{ $t('reader.audio_open') }}
              </v-btn>
            </div>
          </template>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
const API_PRESETS = {
  chat_completions: {
    url: 'https://api.xiaomimimo.com/v1/chat/completions',
    model: 'mimo-v2.5-tts',
    auth: 'api-key',
  },
  audio_speech: {
    url: 'https://api.openai.com/v1/audio/speech',
    model: 'tts-1',
    auth: 'bearer',
  },
  custom: {
    url: '',
    model: '',
    auth: 'bearer',
  },
};

export default {
  data: () => ({
    query: '',
    books: [],
    searching: false,
    searched: false,
    selected: null,

    apiType: 'chat_completions',
    apiUrl: API_PRESETS.chat_completions.url,
    modelName: API_PRESETS.chat_completions.model,
    authType: API_PRESETS.chat_completions.auth,
    apiKey: '',
    voiceType: 'default',
    customVoice: '',
    voiceName: 'alloy',
    processing: false,
    resultMsg: '',
    resultType: 'success',
    completed: false,
  }),
  computed: {
    apiTypeOptions() {
      const t = this.$t.bind(this);
      return [
        { value: 'chat_completions', label: t('mimoTts.apiTypeChat') },
        { value: 'audio_speech', label: t('mimoTts.apiTypeSpeech') },
        { value: 'custom', label: t('mimoTts.apiTypeCustom') },
      ];
    },
    authTypeOptions() {
      const t = this.$t.bind(this);
      return [
        { value: 'api-key', label: t('mimoTts.authTypeApiKey') },
        { value: 'bearer', label: t('mimoTts.authTypeBearer') },
      ];
    },
    speechVoiceOptions() {
      const t = this.$t.bind(this);
      const voices = ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'];
      return voices.map((v) => ({
        value: v,
        label: t(`mimoTts.voiceSpeech_${v}`),
      }));
    },
    voiceOptions() {
      const t = this.$t.bind(this);
      return [
        { value: 'default', label: t('mimoTts.voiceDefault') },
        { value: 'gentle', label: t('mimoTts.voiceGentle') },
        { value: 'calm', label: t('mimoTts.voiceCalm') },
        { value: 'lively', label: t('mimoTts.voiceLively') },
        { value: 'custom', label: t('mimoTts.voiceCustom') },
      ];
    },
    voiceDesc() {
      if (this.voiceType === 'custom') {
        return this.customVoice.trim() || '';
      }
      const descs = {
        default: '自然平和的语调，语速适中，咬字清晰',
        gentle: '温柔细腻的语调，语速偏慢，咬字清晰，富有亲和力',
        calm: '沉稳厚重的语调，语速适中偏低，字正腔圆，富有磁性',
        lively: '活泼轻快的语调，语速偏快，情绪饱满，句尾音调上扬',
      };
      return descs[this.voiceType] || descs.default;
    },
    canConvert() {
      return (
        this.selected &&
        (this.selected.files || []).some((f) => f.format === 'EPUB') &&
        this.apiKey.trim() &&
        this.apiUrl.trim() &&
        this.modelName.trim()
      );
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    onApiTypeChange(type) {
      const preset = API_PRESETS[type];
      if (preset) {
        this.apiUrl = preset.url;
        this.modelName = preset.model;
        this.authType = preset.auth;
      }
    },
    async search() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.selected = null;
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.books = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (_e) {
        this.books = [];
      } finally {
        this.searching = false;
        this.searched = true;
      }
    },
    clearSearch() {
      this.books = [];
      this.selected = null;
      this.searched = false;
      this.resultMsg = '';
      this.completed = false;
    },
    selectBook(book) {
      this.selected = this.selected && this.selected.id === book.id ? null : book;
      this.resultMsg = '';
      this.completed = false;
    },
    async startConvert() {
      if (!this.canConvert) return;
      this.resultMsg = '';
      this.completed = false;
      this.processing = true;
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/convert', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_id: this.selected.id,
            api_key: this.apiKey.trim(),
            voice_desc: this.voiceDesc,
            api_url: this.apiUrl.trim(),
            model_name: this.modelName.trim(),
            api_type: this.apiType,
            voice_name: this.apiType === 'audio_speech' ? this.voiceName : '',
            auth_type: this.authType,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('mimoTts.convertStarted');
          this.resultType = 'success';
          this.completed = true;
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.processing = false;
      }
    },
  },
};
</script>

<style scoped>
.mt-card {
  border: 2px solid #90CAF9;
}

.mt-book-list {
  max-height: 320px;
  overflow-y: auto;
}

.mt-list {
  background: transparent !important;
}

.mt-book-item {
  border-radius: 8px !important;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.mt-book-item:hover {
  background: rgba(144, 202, 249, 0.15) !important;
}

.mt-book-selected {
  background: rgba(144, 202, 249, 0.25) !important;
  border: 1px solid #90CAF9;
}

.mt-book-title {
  font-size: 13px !important;
  white-space: normal !important;
  line-height: 1.3;
}

.mt-book-author {
  font-size: 11px !important;
}

.mt-start-btn {
  width: 60%;
  min-width: 180px;
}

.mt-fade-enter-active,
.mt-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.mt-fade-enter,
.mt-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
