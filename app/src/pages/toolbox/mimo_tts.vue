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
              {{ $t('mimoTts.noResults') }}
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

            <v-select
              v-model="apiType"
              :label="$t('mimoTts.apiType')"
              :items="apiTypeOptions"
              item-text="label"
              item-value="value"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-api"
              @update:model-value="onApiTypeChange"
            />

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

            <v-text-field
              v-model="modelName"
              :label="$t('mimoTts.modelName')"
              :placeholder="$t('mimoTts.modelNamePlaceholder')"
              :disabled="apiType === 'chat_completions'"
              :hint="apiType === 'chat_completions' ? $t('mimoTts.modelFixed') : ''"
              persistent-hint
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-chip"
            />

            <v-select
              v-model="authType"
              :label="$t('mimoTts.authType')"
              :items="authTypeOptions"
              item-text="label"
              item-value="value"
              outlined
              dense
              hide-details
              class="mb-3"
              prepend-inner-icon="mdi-shield-key"
            />

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

            <template v-if="apiType === 'chat_completions'">
              <v-radio-group v-model="voiceType" dense row class="mb-2 mt-1">
                <v-radio :label="$t('mimoTts.voicePreset')" value="preset" />
                <v-radio :label="$t('mimoTts.voiceCustom')" value="custom" />
                <v-radio :label="$t('mimoTts.voiceClone')" value="clone" />
              </v-radio-group>

              <div v-if="voiceType === 'preset'" class="mb-4">
                <v-select
                  v-model="presetVoiceId"
                  :label="$t('mimoTts.voicePresetSelect')"
                  :items="presetVoiceOptions"
                  item-text="name"
                  item-value="id"
                  outlined
                  dense
                  hide-details
                  class="mb-2"
                  prepend-inner-icon="mdi-account-voice"
                />
                <div class="d-flex align-center">
                  <v-btn
                    small
                    color="primary"
                    variant="outlined"
                    :disabled="!presetVoiceId"
                    @click="togglePresetSample"
                  >
                    <v-icon small left>{{ playingSample === presetVoiceId ? 'mdi-stop' : 'mdi-play' }}</v-icon>
                    {{ playingSample === presetVoiceId ? $t('mimoTts.voiceStopSample') : $t('mimoTts.voicePlaySample') }}
                  </v-btn>
                  <span class="text-caption grey--text ml-2">{{ presetVoiceLang }}</span>
                </div>
              </div>

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
                class="mb-2"
              />

              <div v-if="voiceType === 'custom'" class="mb-4">
                <div class="d-flex align-center mb-1">
                  <v-text-field
                    v-model="promptNameInput"
                    :label="$t('mimoTts.promptName')"
                    :placeholder="$t('mimoTts.promptNamePlaceholder')"
                    outlined
                    dense
                    hide-details
                    class="mr-2"
                  />
                  <v-btn
                    small
                    color="secondary"
                    variant="outlined"
                    :loading="promptSaving"
                    :disabled="!promptNameInput.trim() || !customVoice.trim()"
                    @click="savePrompt"
                  >
                    <v-icon left small>mdi-content-save</v-icon>{{ $t('mimoTts.promptSave') }}
                  </v-btn>
                </div>
                <div class="text-subtitle-2 mb-1 mt-3">{{ $t('mimoTts.promptList') }}</div>
                <div v-if="prompts.length === 0" class="text-caption grey--text mb-1">
                  {{ $t('mimoTts.promptEmpty') }}
                </div>
                <v-list v-else dense class="pa-0">
                  <v-list-item
                    v-for="p in prompts"
                    :key="p.name"
                    :class="{ 'mt-clone-selected': promptNameInput === p.name }"
                    @click="applyPrompt(p)"
                  >
                    <v-list-item-content>
                      <v-list-item-title class="mt-book-title">{{ p.name }}</v-list-item-title>
                      <v-list-item-subtitle class="text-caption grey--text text-truncate">{{ p.desc }}</v-list-item-subtitle>
                    </v-list-item-content>
                    <v-list-item-action class="flex-row align-center">
                      <v-icon small class="mr-2" @click.stop="deletePrompt(p.name)">mdi-delete</v-icon>
                      <v-icon small color="primary" @click.stop="applyPrompt(p)">mdi-application</v-icon>
                    </v-list-item-action>
                  </v-list-item>
                </v-list>
              </div>

              <div v-if="voiceType === 'clone'" class="mb-4">
                <div class="d-flex align-center mb-2">
                  <v-text-field
                    v-model="cloneNameInput"
                    :label="$t('mimoTts.cloneName')"
                    :placeholder="$t('mimoTts.cloneNamePlaceholder')"
                    outlined
                    dense
                    hide-details
                    class="mr-2"
                  />
                  <input
                    ref="cloneFileInput"
                    type="file"
                    accept=".mp3,.wav"
                    class="d-none"
                    @change="onCloneFileChange"
                  />
                  <v-btn color="secondary" variant="outlined" @click="$refs.cloneFileInput.click()">
                    <v-icon left small>mdi-paperclip</v-icon>{{ $t('mimoTts.cloneChooseBtn') }}
                  </v-btn>
                </div>
                <div class="text-caption grey--text mb-2">
                  {{ selectedCloneFile ? selectedCloneFile.name : $t('mimoTts.cloneChooseFile') }}
                </div>
                <v-btn
                  block
                  small
                  color="primary"
                  :loading="cloneUploading"
                  :disabled="!cloneNameInput.trim() || !selectedCloneFile"
                  @click="uploadClone"
                >
                  <v-icon left>mdi-upload</v-icon>{{ $t('mimoTts.cloneUpload') }}
                </v-btn>

                <v-divider class="my-3" />

                <div class="text-subtitle-2 mb-2">{{ $t('mimoTts.cloneList') }}</div>
                <div v-if="clones.length === 0" class="text-caption grey--text mb-2">
                  {{ $t('mimoTts.cloneEmpty') }}
                </div>
                <v-list v-else dense class="pa-0">
                  <v-list-item
                    v-for="c in clones"
                    :key="c.name"
                    :class="{ 'mt-clone-selected': cloneVoice === c.name }"
                    @click="selectClone(c.name)"
                  >
                    <v-list-item-content>
                      <v-list-item-title class="mt-book-title">
                        {{ c.name }}
                        <span class="text-caption grey--text">({{ c.ext }}, {{ formatSize(c.size) }})</span>
                      </v-list-item-title>
                    </v-list-item-content>
                    <v-list-item-action class="flex-row align-center">
                      <v-icon
                        small
                        :color="playingClone === c.name ? 'primary' : ''"
                        class="mr-2"
                        @click.stop="toggleCloneSample(c.name)"
                      >
                        {{ playingClone === c.name ? 'mdi-stop' : 'mdi-play' }}
                      </v-icon>
                      <v-icon small class="mr-2" @click.stop="deleteClone(c.name)">mdi-delete</v-icon>
                      <v-icon
                        small
                        :color="cloneVoice === c.name ? 'primary' : 'grey lighten-1'"
                        @click.stop="selectClone(c.name)"
                      >
                        {{ cloneVoice === c.name ? 'mdi-check-circle' : 'mdi-circle-outline' }}
                      </v-icon>
                    </v-list-item-action>
                  </v-list-item>
                </v-list>
                <v-chip v-if="cloneVoice" small color="primary" class="mt-2">
                  {{ $t('mimoTts.cloneSelected') }}：{{ cloneVoice }}
                </v-chip>
              </div>
            </template>

            <template v-else-if="apiType === 'audio_speech'">
              <v-select
                v-model="voiceName"
                :label="$t('mimoTts.voiceName')"
                :items="speechVoiceOptions"
                item-text="label"
                item-value="value"
                outlined
                dense
                hide-details
                class="mb-4"
                prepend-inner-icon="mdi-account-voice"
              />
            </template>

            <template v-else>
              <v-select
                v-model="voiceType"
                :label="$t('mimoTts.voiceLabel')"
                :items="voiceOptions"
                item-text="label"
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

            <div class="d-flex justify-center flex-wrap mt-btn-row">
              <v-btn
                color="secondary"
                variant="outlined"
                class="mt-test-btn"
                :loading="testing"
                :disabled="!apiKey.trim() || !apiUrl.trim() || !modelName.trim()"
                @click="testConnection"
              >
                <v-icon left>mdi-connection</v-icon>
                {{ testing ? $t('mimoTts.testTesting') : $t('mimoTts.testBtn') }}
              </v-btn>

              <v-btn
                color="primary"
                class="mt-start-btn"
                :loading="processing"
                :disabled="processing || !canConvert"
                @click="startConvert"
              >
                <v-icon left>mdi-headphones</v-icon>
                {{ $t('mimoTts.startBtn') }}
              </v-btn>
            </div>

            <div v-if="processing || completed" class="mt-4">
              <div class="mb-1 d-flex justify-space-between text-caption">
                <span>{{ status === 'completed' ? $t('mimoTts.statusCompleted') : $t('mimoTts.statusProcessing') }}</span>
                <span>{{ progress }}%</span>
              </div>
              <v-progress-linear v-model="progress" height="10" rounded color="primary" />
            </div>

            <div v-if="completed" class="d-flex justify-center mt-4">
              <v-btn
                color="success"
                outlined
                @click="$router.push('/audio/' + selected.id)"
              >
                <v-icon left>mdi-headphones</v-icon>
                {{ $t('mimoTts.audioOpen') }}
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

const PRESET_VOICES = [
  { id: 'mimo_default', name: 'MiMo-默认', lang: 'zh', gender: 'female', sample: 'mimo_default.wav' },
  { id: '冰糖', name: '冰糖', lang: 'zh', gender: 'female', sample: 'bingtang.wav' },
  { id: '茉莉', name: '茉莉', lang: 'zh', gender: 'female', sample: 'moli.wav' },
  { id: '苏打', name: '苏打', lang: 'zh', gender: 'male', sample: 'souda.wav' },
  { id: '白桦', name: '白桦', lang: 'zh', gender: 'male', sample: 'baihua.wav' },
  { id: 'Mia', name: 'Mia', lang: 'en', gender: 'female', sample: 'Mia.wav' },
  { id: 'Chloe', name: 'Chloe', lang: 'en', gender: 'female', sample: 'Chloe.wav' },
  { id: 'Milo', name: 'Milo', lang: 'en', gender: 'male', sample: 'Milo.wav' },
  { id: 'Dean', name: 'Dean', lang: 'en', gender: 'male', sample: 'Dean.wav' },
];

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
    voiceType: 'preset',
    presetVoiceId: 'mimo_default',
    customVoice: '',
    voiceName: 'alloy',
    cloneVoice: '',
    clones: [],
    cloneNameInput: '',
    selectedCloneFile: null,
    cloneUploading: false,
    prompts: [],
    promptNameInput: '',
    promptSaving: false,
    playingSample: '',
    playingClone: '',
    currentAudio: null,

    processing: false,
    testing: false,
    resultMsg: '',
    resultType: 'success',
    completed: false,
    progress: 0,
    status: '',
    pollInterval: null,
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
      return ['alloy', 'echo', 'fable', 'onyx', 'nova', 'shimmer'].map((v) => ({
        value: v,
        label: t(`mimoTts.voiceSpeech_${v}`),
      }));
    },
    presetVoiceOptions() {
      return PRESET_VOICES.map((v) => ({
        id: v.id,
        name: v.name,
        lang: v.lang,
        gender: v.gender,
        sample: v.sample,
      }));
    },
    presetVoiceLang() {
      const v = PRESET_VOICES.find((x) => x.id === this.presetVoiceId);
      if (!v) return '';
      const t = this.$t.bind(this);
      const lang = v.lang === 'zh' ? t('mimoTts.presetLangZh') : t('mimoTts.presetLangEn');
      const gender = v.gender === 'female' ? t('mimoTts.presetGenderFemale') : t('mimoTts.presetGenderMale');
      return `${lang} · ${gender}`;
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
      return descs[this.voiceType] || '';
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
  async created() {
    this.$store.commit('navbar', true);
    await this.loadSavedConfig();
    await this.loadClones();
    await this.loadPrompts();
  },
  beforeDestroy() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
    this.stopAllAudio();
  },
  methods: {
    onApiTypeChange(type) {
      const preset = API_PRESETS[type];
      if (preset) {
        this.apiUrl = preset.url;
        this.modelName = preset.model;
        this.authType = preset.auth;
      }
      if (type === 'chat_completions') {
        this.modelName = API_PRESETS.chat_completions.model;
      }
      if (type === 'custom') this.voiceType = 'custom';
      this.stopAllAudio();
    },
    async loadSavedConfig() {
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/config');
        if (rsp.err === 'ok' && rsp.config) {
          const c = rsp.config;
          this.apiKey = c.api_key || '';
          this.apiUrl = c.api_url || this.apiUrl;
          this.modelName = c.model_name || this.modelName;
          this.apiType = c.api_type || this.apiType;
          this.voiceName = c.voice_name || 'alloy';
          this.authType = c.auth_type || this.authType;
          if (c.clone_voice) {
            this.voiceType = 'clone';
            this.cloneVoice = c.clone_voice;
          } else if (c.voice_desc) {
            const presetMatch = {
              '自然平和的语调，语速适中，咬字清晰': 'default',
              '温柔细腻的语调，语速偏慢，咬字清晰，富有亲和力': 'gentle',
              '沉稳厚重的语调，语速适中偏低，字正腔圆，富有磁性': 'calm',
              '活泼轻快的语调，语速偏快，情绪饱满，句尾音调上扬': 'lively',
            };
            const matched = presetMatch[c.voice_desc];
            if (matched) {
              this.voiceType = 'custom';
              this.customVoice = '';
            } else {
              this.voiceType = 'custom';
              this.customVoice = c.voice_desc;
            }
          } else if (c.voice_name) {
            const preset = PRESET_VOICES.find((v) => v.id === c.voice_name);
            if (preset) {
              this.voiceType = 'preset';
              this.presetVoiceId = c.voice_name;
            }
          }
          this.resultMsg = this.$t('mimoTts.configLoaded');
          this.resultType = 'info';
          if (this.apiType === 'chat_completions') {
            this.modelName = API_PRESETS.chat_completions.model;
          }
        }
      } catch (_e) {
      }
    },
    async testConnection() {
      this.testing = true;
      this.resultMsg = '';
      this.completed = false;
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            api_key: this.apiKey.trim(),
            voice_desc: this.voiceDesc,
            api_url: this.apiUrl.trim(),
            model_name: this.modelName.trim(),
            api_type: this.apiType,
            voice_name: this.apiType === 'audio_speech' ? this.voiceName : (this.voiceType === 'preset' ? this.presetVoiceId : ''),
            auth_type: this.authType,
            clone_voice: this.voiceType === 'clone' ? this.cloneVoice : '',
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('mimoTts.testSuccess');
          this.resultType = 'success';
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.testing = false;
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
      this.stopAllAudio();
    },
    selectBook(book) {
      this.selected = this.selected && this.selected.id === book.id ? null : book;
      this.resultMsg = '';
      this.completed = false;
      this.stopAllAudio();
    },
    async startConvert() {
      if (!this.canConvert) return;
      this.resultMsg = '';
      this.completed = false;
      this.processing = true;
      this.progress = 0;
      this.status = '';
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
            voice_name: this.apiType === 'audio_speech' ? this.voiceName : (this.voiceType === 'preset' ? this.presetVoiceId : ''),
            auth_type: this.authType,
            clone_voice: this.voiceType === 'clone' ? this.cloneVoice : '',
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('mimoTts.convertStarted');
          this.resultType = 'success';
          this.pollProgress();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
          this.processing = false;
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
        this.processing = false;
      }
    },
    onCloneFileChange(event) {
      const file = event.target.files && event.target.files[0] ? event.target.files[0] : null;
      if (!file) return;
      const ext = file.name.split('.').pop().toLowerCase();
      if (ext !== 'mp3' && ext !== 'wav') {
        this.resultMsg = this.$t('mimoTts.fileTypeInvalid');
        this.resultType = 'error';
        if (this.$refs.cloneFileInput) this.$refs.cloneFileInput.value = '';
        return;
      }
      if (file.size > 7 * 1024 * 1024) {
        this.resultMsg = this.$t('mimoTts.fileTooLarge');
        this.resultType = 'error';
        if (this.$refs.cloneFileInput) this.$refs.cloneFileInput.value = '';
        return;
      }
      this.selectedCloneFile = file;
    },
    async loadClones() {
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/clone/list');
        this.clones = rsp.err === 'ok' ? (rsp.clones || []) : [];
      } catch (_e) {
        this.clones = [];
      }
    },
    async loadPrompts() {
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/prompt/list');
        this.prompts = rsp.err === 'ok' ? (rsp.prompts || []) : [];
      } catch (_e) {
        this.prompts = [];
      }
    },
    async savePrompt() {
      const name = this.promptNameInput.trim();
      const desc = this.customVoice.trim();
      if (!name || !desc || this.promptSaving) return;
      this.promptSaving = true;
      this.resultMsg = '';
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/prompt/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name, desc }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg;
          this.resultType = 'success';
          await this.loadPrompts();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.promptSaving = false;
      }
    },
    async deletePrompt(name) {
      if (!window.confirm(this.$t('mimoTts.promptDeleteConfirm'))) return;
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/prompt/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name }),
        });
        if (rsp.err === 'ok') {
          if (this.promptNameInput === name) this.promptNameInput = '';
          await this.loadPrompts();
          this.resultMsg = rsp.msg;
          this.resultType = 'success';
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
    applyPrompt(p) {
      this.voiceType = 'custom';
      this.customVoice = p.desc;
      this.promptNameInput = p.name;
      this.resultMsg = '';
    },
    async uploadClone() {
      const name = this.cloneNameInput.trim();
      if (!name || !this.selectedCloneFile) return;
      this.cloneUploading = true;
      this.resultMsg = '';
      try {
        const fd = new FormData();
        fd.append('voice_name', name);
        fd.append('file', this.selectedCloneFile);
        const resp = await fetch('/api/toolbox/mimo_tts/clone/upload', {
          method: 'POST',
          body: fd,
        });
        const rsp = await resp.json();
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('mimoTts.cloneUploaded');
          this.resultType = 'success';
          this.selectedCloneFile = null;
          if (this.$refs.cloneFileInput) this.$refs.cloneFileInput.value = '';
          this.voiceType = 'clone';
          this.cloneVoice = rsp.data.name;
          await this.loadClones();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.cloneUploading = false;
      }
    },
    async deleteClone(name) {
      if (!window.confirm(this.$t('mimoTts.cloneDeleteConfirm'))) return;
      try {
        const rsp = await this.$backend('/toolbox/mimo_tts/clone/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ voice_name: name }),
        });
        if (rsp.err === 'ok') {
          if (this.cloneVoice === name) this.cloneVoice = '';
          await this.loadClones();
          this.resultMsg = rsp.msg;
          this.resultType = 'success';
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
    selectClone(name) {
      this.voiceType = 'clone';
      this.cloneVoice = name;
      this.resultMsg = '';
    },
    togglePresetSample() {
      if (this.playingSample === this.presetVoiceId) {
        this.stopAllAudio();
        return;
      }
      this.stopAllAudio();
      const v = PRESET_VOICES.find((x) => x.id === this.presetVoiceId);
      if (!v) return;
      this.playingSample = v.id;
      this.currentAudio = new Audio(`/static/mimo_tts/samples/${v.sample}`);
      this.bindAudioEvents();
      this.currentAudio.play().catch(() => this.onAudioError());
    },
    toggleCloneSample(name) {
      if (this.playingClone === name) {
        this.stopAllAudio();
        return;
      }
      this.stopAllAudio();
      this.playingClone = name;
      this.currentAudio = new Audio(`/api/toolbox/mimo_tts/clone/audio?voice_name=${encodeURIComponent(name)}`);
      this.bindAudioEvents();
      this.currentAudio.play().catch(() => this.onAudioError());
    },
    bindAudioEvents() {
      this.currentAudio.addEventListener('ended', () => this.stopAllAudio());
      this.currentAudio.addEventListener('error', () => this.onAudioError());
    },
    stopAllAudio() {
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio = null;
      }
      this.playingSample = '';
      this.playingClone = '';
    },
    onAudioError() {
      this.stopAllAudio();
      this.resultMsg = this.$t('mimoTts.audioPlayFailed');
      this.resultType = 'error';
    },
    formatSize(size) {
      if (!size && size !== 0) return '0B';
      if (size < 1024) return `${size}B`;
      if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)}KB`;
      return `${(size / 1024 / 1024).toFixed(1)}MB`;
    },
    pollProgress() {
      if (this.pollInterval) {
        clearInterval(this.pollInterval);
      }
      this.pollInterval = setInterval(async () => {
        try {
          const rsp = await this.$backend('/toolbox/mimo_tts/progress');
          if (rsp.err === 'ok' && rsp.data) {
            this.progress = rsp.data.progress || 0;
            this.status = rsp.data.status || '';
            if (rsp.data.status === 'completed') {
              clearInterval(this.pollInterval);
              this.pollInterval = null;
              this.processing = false;
              this.completed = true;
              this.resultMsg = rsp.msg || this.$t('mimoTts.convertCompleted');
              this.resultType = 'success';
            } else if (rsp.data.status === 'failed') {
              clearInterval(this.pollInterval);
              this.pollInterval = null;
              this.processing = false;
              this.resultMsg = rsp.msg || this.$t('mimoTts.convertFailed');
              this.resultType = 'error';
            }
          } else {
            clearInterval(this.pollInterval);
            this.pollInterval = null;
            this.processing = false;
            this.resultMsg = rsp.msg || rsp.err;
            this.resultType = 'error';
          }
        } catch (e) {
          clearInterval(this.pollInterval);
          this.pollInterval = null;
          this.processing = false;
          this.resultMsg = String(e);
          this.resultType = 'error';
        }
      }, 2000);
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

.mt-clone-selected {
  background: rgba(144, 202, 249, 0.25) !important;
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
  min-width: 180px;
}

.mt-test-btn {
  min-width: 140px;
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
