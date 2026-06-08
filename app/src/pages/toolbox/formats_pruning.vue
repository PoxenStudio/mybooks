<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('formatsPruning.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('formatsPruning.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Tool card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="fp-card pa-6">
          <!-- Options -->
          <p class="fp-options-title mb-2">{{ $t('formatsPruning.optionsTitle') }}</p>

          <v-checkbox
            v-for="opt in options"
            :key="opt.key"
            v-model="selected"
            :label="$t(opt.labelKey)"
            :value="opt.key"
            dense
            hide-details
            class="mt-1"
          ></v-checkbox>

          <v-alert v-if="allSelected" type="warning" dense outlined class="mt-4 mb-0">
            {{ $t('formatsPruning.allSelectedError') }}
          </v-alert>

          <!-- Start button -->
          <div class="d-flex justify-center mt-6">
            <v-btn
              color="primary"
              class="fp-start-btn"
              :loading="processing"
              :disabled="processing || allSelected || selected.length === 0"
              @click="startPrune"
            >
              {{ $t('formatsPruning.startBtn') }}
            </v-btn>
          </div>

          <!-- Progress -->
          <div v-if="processing || progress > 0" class="mt-6">
            <div class="mb-2 d-flex justify-space-between text-caption">
              <span>{{ status === 'completed' ? $t('formatsPruning.statusCompleted') : $t('formatsPruning.statusProcessing') }}</span>
              <span>{{ progress }}%</span>
            </div>
            <v-progress-linear
              v-model="progress"
              :color="status === 'completed' ? 'success' : 'primary'"
              height="10"
              rounded
            ></v-progress-linear>
            <div v-if="progressInfo.total" class="text-caption text-grey mt-2 text-center">
              {{ $t('formatsPruning.progressInfo', {
                checked: progressInfo.checked,
                total: progressInfo.total,
                books: progressInfo.pruned_books,
                formats: progressInfo.pruned_formats,
              }) }}
            </div>
          </div>

          <!-- Result message -->
          <transition name="fade">
            <v-alert
              v-if="resultMsg"
              :type="resultType"
              dense
              text
              rounded="lg"
              class="mt-6 mb-0"
            >{{ resultMsg }}</v-alert>
          </transition>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    options: [
      { key: 'pdf', labelKey: 'formatsPruning.optPdf' },
      { key: 'epub', labelKey: 'formatsPruning.optEpub' },
      { key: 'azw3_mobi', labelKey: 'formatsPruning.optAzw3Mobi' },
      { key: 'txt', labelKey: 'formatsPruning.optTxt' },
      { key: 'docx', labelKey: 'formatsPruning.optDocx' },
    ],
    selected: ['azw3_mobi'],

    processing: false,
    progress: 0,
    status: '', // '', 'running', 'completed', 'error'
    progressInfo: {},

    resultMsg: '',
    resultType: 'success',
    pollInterval: null,
  }),
  computed: {
    allSelected() {
      return this.selected.length >= this.options.length;
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  beforeDestroy() {
    if (this.pollInterval) clearInterval(this.pollInterval);
  },
  methods: {
    async startPrune() {
      if (this.allSelected) {
        this.resultMsg = this.$t('formatsPruning.allSelectedError');
        this.resultType = 'error';
        return;
      }

      this.resultMsg = '';
      this.processing = true;
      this.progress = 0;
      this.status = 'running';
      this.progressInfo = {};

      try {
        const rsp = await this.$backend('/toolbox/formats_pruning/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ delete: this.selected }),
        });

        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('formatsPruning.processStartSuccess');
          this.resultType = 'success';
          this.pollProgress();
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
          this.processing = false;
          this.status = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
        this.processing = false;
        this.status = 'error';
      }
    },
    pollProgress() {
      if (this.pollInterval) clearInterval(this.pollInterval);

      this.pollInterval = setInterval(async () => {
        try {
          const rsp = await this.$backend('/toolbox/formats_pruning/progress');

          if (rsp.err === 'ok') {
            const data = rsp.data;
            this.progress = data.progress;
            this.progressInfo = data;

            if (data.status === 'completed') {
              this.status = 'completed';
              this.processing = false;
              clearInterval(this.pollInterval);
              this.resultMsg = rsp.msg || this.$t('formatsPruning.processCompleted');
              this.resultType = 'success';
            }
          } else {
            this.resultMsg = rsp.msg || rsp.err;
            this.resultType = 'error';
            this.processing = false;
            this.status = 'error';
            clearInterval(this.pollInterval);
          }
        } catch (e) {
          this.resultMsg = String(e);
          this.resultType = 'error';
          this.processing = false;
          this.status = 'error';
          clearInterval(this.pollInterval);
        }
      }, 2000);
    },
  },
};
</script>

<style scoped>
.fp-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

.fp-options-title {
  font-size: 14px;
  line-height: 1.7;
  color: #606880;
  margin: 0;
}
.theme--dark .fp-options-title {
  color: #8892a4;
}

.text-grey {
  color: #606880;
}
.theme--dark .text-grey {
  color: #8892a4;
}

.fp-start-btn {
  width: 33%;
  min-width: 160px;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.fade-enter,
.fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
