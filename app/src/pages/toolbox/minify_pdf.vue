<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('minifyPdf.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('minifyPdf.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Main content card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="minify-card pa-6">

          <!-- Upload Area -->
          <div v-if="!uploadedFilename" class="mb-4">
            <v-file-input
              v-model="file"
              :label="$t('minifyPdf.uploadLabel')"
              accept="application/pdf"
              outlined
              dense
              prepend-icon="mdi-file-pdf-box"
              @change="handleFileUpload"
              :loading="uploading"
              :disabled="uploading"
            ></v-file-input>
          </div>

          <!-- Uploaded Info & Configurations -->
          <div v-if="uploadedFilename" class="mb-4">
            <v-alert type="success" dense outlined class="mb-4">
              {{ $t('minifyPdf.uploadedFile') }}: {{ uploadedFilename }}<br>
              {{ $t('minifyPdf.pageCount') }}: {{ pdfInfo.page_count }},
              {{ $t('minifyPdf.fileSize') }}: {{ formatBytes(pdfInfo.file_size) }}
            </v-alert>

            <!-- Mode Selection -->
            <v-radio-group v-model="mode" :label="$t('minifyPdf.modeLabel')" row hide-details>
              <v-radio :label="$t('minifyPdf.modeGray')" value="gray"></v-radio>
              <v-radio :label="$t('minifyPdf.modeBw')" value="bw"></v-radio>
            </v-radio-group>
            <div class="text-caption mb-3 text-grey">
              <span v-if="mode === 'gray'">{{ $t('minifyPdf.modeGrayDesc') }}</span>
              <span v-else>{{ $t('minifyPdf.modeBwDesc') }}</span>
            </div>

            <!-- Max Brightness (only if gray) -->
            <v-expand-transition>
              <div v-if="mode === 'gray'">
                <v-slider
                  v-model="maxBrightness"
                  :label="$t('minifyPdf.maxBrightnessLabel')"
                  min="150"
                  max="255"
                  thumb-label
                  hide-details
                ></v-slider>
                <div class="text-caption text-grey mt-1">
                  {{ $t('minifyPdf.maxBrightnessDesc') }}
                </div>
              </div>
            </v-expand-transition>

            <!-- Auto Contrast -->
            <v-switch
              v-model="autoContrast"
              :label="$t('minifyPdf.autoContrastLabel')"
              dense
              class="mt-2"
              hide-details
            ></v-switch>
            <div class="text-caption text-grey mb-3">
              {{ $t('minifyPdf.autoContrastDesc') }}
            </div>

            <!-- Max Width -->
            <v-text-field
              v-model.number="maxWidth"
              :label="$t('minifyPdf.maxWidthLabel')"
              type="number"
              min="600"
              max="2048"
              outlined
              dense
              class="mt-4"
              hide-details
              :rules="[v => (v >= 600 && v <= 2048) || $t('minifyPdf.maxWidthError') ]"
            ></v-text-field>
            <div class="text-caption text-grey mb-3 mt-1">
              {{ $t('minifyPdf.maxWidthDesc') }}
            </div>

            <!-- Quality -->
            <v-slider
              v-model="qualify"
              :label="$t('minifyPdf.qualifyLabel')"
              min="60"
              max="95"
              thumb-label
              hide-details
              class="mt-4"
            ></v-slider>
            <div class="text-caption text-grey mb-3">
              {{ $t('minifyPdf.qualifyDesc') }}
            </div>

            <!-- Skip Pages -->
            <v-text-field
              v-model="skipPages"
              :label="$t('minifyPdf.skipPagesLabel')"
              outlined
              dense
              class="mt-4"
              hide-details
              :placeholder="$t('minifyPdf.skipPagesPlaceholder')"
            ></v-text-field>
            <div class="text-caption text-grey mb-3 mt-1">
              {{ $t('minifyPdf.skipPagesDesc') }}
            </div>

            <!-- Drop Pages -->
            <v-text-field
              v-model="dropPages"
              :label="$t('minifyPdf.dropPagesLabel')"
              outlined
              dense
              class="mt-4"
              hide-details
              :placeholder="$t('minifyPdf.dropPagesPlaceholder')"
            ></v-text-field>
            <div class="text-caption text-grey mb-3 mt-1">
              {{ $t('minifyPdf.dropPagesDesc') }}
            </div>

            <v-btn
              color="primary"
              block
              class="mt-4"
              @click="processPdf"
              :loading="processing"
              :disabled="processing || status === 'completed'"
            >
              {{ $t('minifyPdf.processBtn') }}
            </v-btn>
          </div>

          <!-- Progress -->
          <div v-if="processing || progress > 0" class="mt-6">
            <div class="mb-2 d-flex justify-space-between text-caption">
              <span>{{ status === 'completed' ? $t('minifyPdf.statusCompleted') : $t('minifyPdf.statusProcessing') }}</span>
              <span>{{ progress }}%</span>
            </div>
            <v-progress-linear
              v-model="progress"
              :color="status === 'completed' ? 'success' : 'primary'"
              height="10"
              rounded
            ></v-progress-linear>
          </div>

          <!-- Download Button -->
          <div v-if="status === 'completed' && downloadUrl" class="mt-6 text-center">
            <v-btn
              color="success"
              large
              :href="downloadUrl"
              target="_blank"
            >
              <v-icon left>mdi-download</v-icon>
              {{ $t('minifyPdf.downloadBtn') }}
            </v-btn>
          </div>

          <!-- Result message -->
          <transition name="fade">
            <v-alert
              v-if="resultMsg"
              :type="resultType"
              dense
              text
              rounded="lg"
              class="mt-4 mb-0"
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
    file: null,
    uploading: false,
    uploadedFilename: '',
    pdfInfo: {},

    mode: 'gray', // 'gray' or 'bw'
    maxBrightness: 200,

    maxWidth: 1200,
    autoContrast: true,
    skipPages: '',
    dropPages: '',
    qualify: 75,

    processing: false,
    progress: 0,
    status: '', // '', 'running', 'completed', 'error'
    downloadUrl: '',

    resultMsg: '',
    resultType: 'success',
    pollInterval: null,
  }),
  created() {
    this.$store.commit('navbar', true);
  },
  beforeDestroy() {
    if (this.pollInterval) clearInterval(this.pollInterval);
  },
  methods: {
    formatBytes(bytes, decimals = 2) {
      if (!+bytes) return '0 Bytes';
      const k = 1024;
      const dm = decimals < 0 ? 0 : decimals;
      const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return `${parseFloat((bytes / Math.pow(k, i)).toFixed(dm))} ${sizes[i]}`;
    },
    async handleFileUpload() {
      if (!this.file) return;
      this.uploading = true;
      this.resultMsg = '';

      const formData = new FormData();
      formData.append('file', this.file);

      try {
        const response = await fetch('/api/toolbox/minify_pdf/upload', {
          method: 'POST',
          body: formData,
        });
        const rsp = await response.json();

        if (rsp.err === 'ok') {
          this.uploadedFilename = rsp.data.filename;
          this.pdfInfo = rsp.data;
          this.resultMsg = this.$t('minifyPdf.uploadSuccess');
          this.resultType = 'success';
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.uploading = false;
      }
    },
    async processPdf() {
      if (this.maxWidth < 600 || this.maxWidth > 2048) {
        this.resultMsg = this.$t('minifyPdf.maxWidthError');
        this.resultType = 'error';
        return;
      }

      this.resultMsg = '';
      this.processing = true;
      this.progress = 0;
      this.status = 'running';
      this.downloadUrl = '';

      const params = {
        bw: this.mode === 'bw',
        gray: this.mode === 'gray',
        max_width: this.maxWidth,
        auto: this.autoContrast,
        qualify: this.qualify,
      };

      if (this.skipPages) params.skip_pages = this.skipPages;
      if (this.dropPages) params.drop_pages = this.dropPages;

      if (this.mode === 'gray') {
        params.max_brightness = this.maxBrightness;
      }

      try {
        const rsp = await this.$backend('/toolbox/minify_pdf/process', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: this.uploadedFilename,
            params: params
          }),
        });

        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('minifyPdf.processStartSuccess');
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
          const rsp = await this.$backend(`/toolbox/minify_pdf/progress?filename=${this.uploadedFilename}`);

          if (rsp.err === 'ok') {
            const data = rsp.data;
            this.progress = data.progress;

            if (data.status === 'completed') {
              this.status = 'completed';
              this.downloadUrl = data.download_url;
              this.processing = false;
              clearInterval(this.pollInterval);
              this.resultMsg = rsp.msg || this.$t('minifyPdf.processCompleted');
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
    }
  },
};
</script>

<style scoped>
.minify-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

.text-grey {
  color: #606880;
}
.theme--dark .text-grey {
  color: #8892a4;
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
