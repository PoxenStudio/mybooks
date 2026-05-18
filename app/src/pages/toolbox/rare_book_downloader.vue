<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col>
        <span class="text-h5 font-weight-bold">{{ $t('rareBookDownloader.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('rareBookDownloader.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Search card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="rbd-card pa-6">
          <!-- Icon + title inside card -->
          <div class="d-flex align-center justify-center mb-6">
            <span class="rbd-icon mr-3">📖</span>
            <span class="text-h5 font-weight-bold rbd-card-title">{{ $t('rareBookDownloader.title') }}</span>
          </div>

          <!-- URL input row -->
          <div class="rbd-search-bar mb-4">
            <input
              v-model="url"
              class="rbd-input"
              type="url"
              :placeholder="$t('rareBookDownloader.placeholder')"
              @keyup.enter="download"
              :disabled="loading"
            />
            <button
              class="rbd-btn-download"
              :class="{ 'rbd-btn-loading': loading }"
              @click="download"
              :disabled="loading"
            >
              <span v-if="loading" class="rbd-spinner" />
              <span v-else>{{ $t('rareBookDownloader.downloadBtn') }}</span>
            </button>
          </div>

          <!-- Result message -->
          <transition name="rbd-fade">
            <v-alert
              v-if="resultMsg"
              :type="resultType"
              dense
              text
              rounded="lg"
              class="mb-4"
            >{{ resultMsg }}</v-alert>
          </transition>

          <!-- Description -->
          <p class="rbd-desc text-caption mb-0">
            {{ $t('rareBookDownloader.descPre') }}<a
              href="https://lbezone.hkust.edu.hk/rse/?s=*&sort=pubyear&order=asc&scopename=thread-bound-books"
              target="_blank"
              rel="noopener noreferrer"
              class="rbd-link"
            >{{ $t('rareBookDownloader.descLibrary') }}</a>{{ $t('rareBookDownloader.descPost') }}
          </p>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    url: '',
    loading: false,
    resultMsg: '',
    resultType: 'success',
  }),
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    async download() {
      this.resultMsg = '';
      const trimmed = this.url.trim();
      if (!trimmed) {
        this.resultMsg = this.$t('rareBookDownloader.errorEmptyUrl');
        this.resultType = 'error';
        return;
      }
      this.loading = true;
      try {
        const rsp = await this.$backend('/admin/toolbox/rare_book_downloader', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: trimmed }),
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('rareBookDownloader.success') : rsp.err);
        this.resultType = rsp.err === 'ok' ? 'success' : 'error';
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.loading = false;
      }
    },
  },
};
</script>

<style scoped>
/* ── Card ── */
.rbd-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

.rbd-icon {
  font-size: 32px;
  line-height: 1;
}

.rbd-card-title {
  color: #003153;
}

.theme--dark .rbd-card-title {
  color: #90caf9;
}

/* ── Search bar ── */
.rbd-search-bar {
  display: flex;
  width: 100%;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 3px 14px rgba(0, 49, 83, 0.13);
}

.rbd-input {
  flex: 1;
  min-width: 0;
  padding: 13px 16px;
  font-size: 14px;
  border: none;
  outline: none;
  background: #f5f7fa;
  color: inherit;
  transition: background 0.2s;
}

.theme--dark .rbd-input {
  background: #1e2130;
  color: #e8eaf0;
}

.rbd-input::placeholder {
  color: #a0aab4;
}

.rbd-input:disabled {
  opacity: 0.6;
}

.rbd-btn-download {
  background: #003153;
  color: #fff;
  border: none;
  padding: 0 24px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  display: flex;
  align-items: center;
  gap: 6px;
  letter-spacing: 0.03em;
  transition: background 0.2s, opacity 0.2s;
  min-width: 88px;
  justify-content: center;
}

.rbd-btn-download:hover:not(:disabled) {
  background: #004a7c;
}

.rbd-btn-download:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

/* ── Spinner ── */
.rbd-spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: rbd-spin 0.7s linear infinite;
}

@keyframes rbd-spin {
  to { transform: rotate(360deg); }
}

/* ── Description ── */
.rbd-desc {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  font-size: 14px !important;
  line-height: 1.65;
  color: #606880;
}

.theme--dark .rbd-desc {
  color: #8892a4;
}

.rbd-link {
  text-decoration: underline;
  text-underline-offset: 2px;
  color: #003153;
}

.theme--dark .rbd-link {
  color: #90caf9;
}

.rbd-link:hover {
  opacity: 0.75;
}

/* ── Transition ── */
.rbd-fade-enter-active,
.rbd-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.rbd-fade-enter,
.rbd-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
