<template>
  <v-container fluid class="pa-4">
    <!-- Page header -->
    <v-row class="mb-3" align="center">
      <v-col class="text-center">
        <span class="text-h5 font-weight-bold">{{ $t('mergeFormats.title') }}</span>
      </v-col>
      <v-col cols="auto">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('mergeFormats.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <!-- Book selection area -->
    <v-row>
      <!-- Left: source book -->
      <v-col cols="12" md="6">
        <v-card rounded="xl" outlined class="mft-panel pa-4">
          <div class="text-subtitle-1 font-weight-bold mb-3 mft-panel-title">
            {{ $t('mergeFormats.sourcePanel') }}
          </div>
          <v-text-field
            v-model="leftQuery"
            :label="$t('mergeFormats.searchPlaceholder')"
            :loading="leftLoading"
            outlined
            dense
            clearable
            hide-details
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="searchLeft"
            @click:clear="clearLeft"
          />
          <div class="mft-book-list">
            <div v-if="leftLoading" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="leftBooks.length === 0 && leftSearched" class="text-center py-6 grey--text">
              {{ $t('mergeFormats.noResults') }}
            </div>
            <v-list v-else dense class="mft-list pa-0">
              <v-list-item
                v-for="book in leftBooks"
                :key="book.id"
                :class="['mft-book-item', { 'mft-book-selected': leftSelected && leftSelected.id === book.id }]"
                @click="selectLeft(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="mft-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="mft-book-author">{{ book.authors.join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      color="primary"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="leftSelected && leftSelected.id === book.id">
                  <v-icon color="primary">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>
        </v-card>
      </v-col>

      <!-- Right: target book -->
      <v-col cols="12" md="6">
        <v-card rounded="xl" outlined class="mft-panel pa-4">
          <div class="text-subtitle-1 font-weight-bold mb-3 mft-panel-title">
            {{ $t('mergeFormats.targetPanel') }}
          </div>
          <v-text-field
            v-model="rightQuery"
            :label="$t('mergeFormats.searchPlaceholder')"
            :loading="rightLoading"
            outlined
            dense
            clearable
            hide-details
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="searchRight"
            @click:clear="clearRight"
          />
          <div class="mft-book-list">
            <div v-if="rightLoading" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="rightBooks.length === 0 && rightSearched" class="text-center py-6 grey--text">
              {{ $t('mergeFormats.noResults') }}
            </div>
            <v-list v-else dense class="mft-list pa-0">
              <v-list-item
                v-for="book in rightBooks"
                :key="book.id"
                :class="['mft-book-item', { 'mft-book-selected': rightSelected && rightSelected.id === book.id }]"
                @click="selectRight(book)"
              >
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="mft-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="mft-book-author">{{ book.authors.join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="file in (book.files || [])"
                      :key="file.format"
                      x-small
                      color="success"
                      outlined
                      class="mr-1"
                    >{{ file.format }}</v-chip>
                  </div>
                </v-list-item-content>
                <v-list-item-action v-if="rightSelected && rightSelected.id === book.id">
                  <v-icon color="success">mdi-check-circle</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Merge action area -->
    <v-row justify="center" class="mt-4">
      <v-col cols="12" md="8" lg="6">
        <!-- Selection summary -->
        <v-card v-if="leftSelected || rightSelected" rounded="lg" outlined class="mft-summary pa-3 mb-3">
          <div class="d-flex align-center flex-wrap" style="gap: 8px;">
            <div class="mft-summary-item" :class="leftSelected ? 'mft-summary-active' : 'mft-summary-empty'">
              <v-icon small class="mr-1">mdi-book-arrow-right-outline</v-icon>
              <span v-if="leftSelected">{{ leftSelected.title }}</span>
              <span v-else class="grey--text">{{ $t('mergeFormats.noSourceSelected') }}</span>
            </div>
            <v-icon color="primary">mdi-arrow-right</v-icon>
            <div class="mft-summary-item" :class="rightSelected ? 'mft-summary-active' : 'mft-summary-empty'">
              <v-icon small class="mr-1">mdi-book-check-outline</v-icon>
              <span v-if="rightSelected">{{ rightSelected.title }}</span>
              <span v-else class="grey--text">{{ $t('mergeFormats.noTargetSelected') }}</span>
            </div>
          </div>
        </v-card>

        <!-- Result message -->
        <transition name="mft-fade">
          <v-alert
            v-if="resultMsg"
            :type="resultType"
            dense
            text
            rounded="lg"
            class="mb-3"
          >{{ resultMsg }}</v-alert>
        </transition>

        <v-btn
          block
          large
          color="primary"
          :disabled="!canMerge || merging"
          :loading="merging"
          @click="doMerge"
        >
          <v-icon left>mdi-merge</v-icon>
          {{ $t('mergeFormats.mergeBtn') }}
        </v-btn>

        <p class="text-caption grey--text text-center mt-3">
          {{ $t('mergeFormats.hint') }}
        </p>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    leftQuery: '',
    leftBooks: [],
    leftLoading: false,
    leftSearched: false,
    leftSelected: null,

    rightQuery: '',
    rightBooks: [],
    rightLoading: false,
    rightSearched: false,
    rightSelected: null,

    merging: false,
    resultMsg: '',
    resultType: 'success',
  }),
  computed: {
    canMerge() {
      return (
        this.leftSelected &&
        this.rightSelected &&
        this.leftSelected.id !== this.rightSelected.id
      );
    },
  },
  created() {
    this.$store.commit('navbar', true);
  },
  methods: {
    async searchLeft() {
      const q = (this.leftQuery || '').trim();
      if (!q) return;
      this.leftLoading = true;
      this.leftSearched = false;
      this.leftSelected = null;
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.leftBooks = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (e) {
        this.leftBooks = [];
      } finally {
        this.leftLoading = false;
        this.leftSearched = true;
      }
    },
    clearLeft() {
      this.leftBooks = [];
      this.leftSelected = null;
      this.leftSearched = false;
    },
    selectLeft(book) {
      this.leftSelected = this.leftSelected && this.leftSelected.id === book.id ? null : book;
    },

    async searchRight() {
      const q = (this.rightQuery || '').trim();
      if (!q) return;
      this.rightLoading = true;
      this.rightSearched = false;
      this.rightSelected = null;
      try {
        const rsp = await this.$backend(`/search?title=title:${encodeURIComponent(q)}`);
        this.rightBooks = rsp.err === 'ok' ? (rsp.books || []) : [];
      } catch (e) {
        this.rightBooks = [];
      } finally {
        this.rightLoading = false;
        this.rightSearched = true;
      }
    },
    clearRight() {
      this.rightBooks = [];
      this.rightSelected = null;
      this.rightSearched = false;
    },
    selectRight(book) {
      this.rightSelected = this.rightSelected && this.rightSelected.id === book.id ? null : book;
    },

    async doMerge() {
      if (!this.canMerge) return;
      this.resultMsg = '';
      this.merging = true;
      try {
        const rsp = await this.$backend('/toolbox/merge_formats/merge', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            source_id: this.leftSelected.id,
            target_id: this.rightSelected.id,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('mergeFormats.mergeSuccess');
          this.resultType = 'success';
          // Remove the merged (source) book from both lists
          const deletedId = rsp.deleted_book_id;
          this.leftBooks = this.leftBooks.filter(b => b.id !== deletedId);
          this.rightBooks = this.rightBooks.filter(b => b.id !== deletedId);
          this.leftSelected = null;
          this.rightSelected = null;
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.resultMsg = String(e);
        this.resultType = 'error';
      } finally {
        this.merging = false;
      }
    },
  },
};
</script>

<style scoped>
/* ── Panel ── */
.mft-panel {
  border: 2px solid #90CAF9;
  transition: box-shadow 0.2s;
  min-height: 380px;
  display: flex;
  flex-direction: column;
}

.mft-panel-title {
  color: #003153;
}

.theme--dark .mft-panel-title {
  color: #90caf9;
}

/* ── Book list ── */
.mft-book-list {
  flex: 1;
  overflow-y: auto;
  max-height: 360px;
}

.mft-list {
  background: transparent !important;
}

.mft-book-item {
  border-radius: 8px !important;
  margin-bottom: 4px;
  cursor: pointer;
  transition: background 0.15s;
}

.mft-book-item:hover {
  background: rgba(144, 202, 249, 0.15) !important;
}

.mft-book-selected {
  background: rgba(144, 202, 249, 0.25) !important;
  border: 1px solid #90CAF9;
}

.mft-book-title {
  font-size: 13px !important;
  white-space: normal !important;
  line-height: 1.3;
}

.mft-book-author {
  font-size: 11px !important;
}

/* ── Summary ── */
.mft-summary {
  border: 1px dashed #90CAF9;
}

.mft-summary-item {
  display: flex;
  align-items: center;
  font-size: 13px;
  padding: 4px 8px;
  border-radius: 6px;
  background: rgba(144, 202, 249, 0.1);
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mft-summary-empty {
  opacity: 0.6;
}

/* ── Fade transition ── */
.mft-fade-enter-active,
.mft-fade-leave-active {
  transition: opacity 0.3s;
}

.mft-fade-enter,
.mft-fade-leave-to {
  opacity: 0;
}
</style>
