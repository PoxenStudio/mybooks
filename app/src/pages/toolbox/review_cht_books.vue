<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('reviewChtBooks.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('reviewChtBooks.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Tool card -->
    <v-row justify="center">
      <v-col cols="12" md="8" lg="6">
        <v-card rounded="xl" outlined class="rcb-card pa-6">
          <!-- Description -->
          <p class="rcb-desc mb-6">{{ $t('reviewChtBooks.description') }}</p>

          <!-- Start button -->
          <div class="d-flex justify-center">
            <button
              class="rcb-btn-start"
              :class="{ 'rcb-btn-loading': loading }"
              :disabled="loading"
              @click="startReview"
            >
              <span v-if="loading" class="rcb-spinner" />
              <span v-else>{{ $t('reviewChtBooks.startBtn') }}</span>
            </button>
          </div>

          <!-- Result message -->
          <transition name="rcb-fade">
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
    loading: false,
    resultMsg: '',
    resultType: 'success',
  }),
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    async startReview() {
      this.resultMsg = '';
      this.loading = true;
      try {
        const rsp = await this.$backend('/toolbox/review_cht_books', {
          method: 'POST',
        });
        this.resultMsg = rsp.msg || (rsp.err === 'ok' ? this.$t('reviewChtBooks.success') : rsp.err);
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
.rcb-card {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
}

/* Description text — 14px normal */
.rcb-desc {
  font-size: 14px;
  line-height: 1.7;
  color: #606880;
  margin: 0;
}

.theme--dark .rcb-desc {
  color: #8892a4;
}

/* Start button */
.rcb-btn-start {
  background: #003153;
  color: #fff;
  border: none;
  padding: 10px 40px;
  font-size: 15px;
  font-weight: 600;
  border-radius: 8px;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  letter-spacing: 0.04em;
  transition: background 0.2s, opacity 0.2s;
  min-width: 140px;
  justify-content: center;
}

.rcb-btn-start:hover:not(:disabled) {
  background: #004a7c;
}

.rcb-btn-start:disabled {
  opacity: 0.65;
  cursor: not-allowed;
}

/* Spinner */
.rcb-spinner {
  display: inline-block;
  width: 15px;
  height: 15px;
  border: 2px solid rgba(255, 255, 255, 0.4);
  border-top-color: #fff;
  border-radius: 50%;
  animation: rcb-spin 0.7s linear infinite;
}

@keyframes rcb-spin {
  to { transform: rotate(360deg); }
}

/* Transition */
.rcb-fade-enter-active,
.rcb-fade-leave-active {
  transition: opacity 0.3s, transform 0.25s;
}
.rcb-fade-enter,
.rcb-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
