<template>
  <v-container fluid class="pa-4 eb-page">
    <!-- Page header -->
    <v-row class="mb-2" align="center">
      <v-col class="py-0">
        <span class="text-h5 font-weight-bold">{{ $t('epubBeautify.title') }}</span>
        <span class="caption grey--text ml-2">{{ $t('epubBeautify.hint') }}</span>
      </v-col>
      <v-col cols="auto" class="py-0">
        <v-btn small color="error" @click="$router.go(-1)">
          <v-icon small left>mdi-close</v-icon>{{ $t('epubBeautify.close') }}
        </v-btn>
      </v-col>
    </v-row>

    <v-row class="mt-2">
      <!-- ═══ 左栏：配置（① 选书 → ② 挑风格 → ③ 微调） ═══ -->
      <v-col cols="12" lg="7" class="pt-0">
        <!-- ─── ① 选书 ─── -->
        <v-card outlined class="eb-card mb-4 pa-5 rounded-lg">
          <div class="d-flex align-center mb-3">
            <span class="eb-stepnum mr-2">1</span>
            <span class="text-subtitle-1 font-weight-bold">{{ $t('epubBeautify.selectBookTitle') }}</span>
          </div>

          <v-text-field
            v-model="query"
            :label="$t('epubBeautify.selectBook')"
            :loading="searching"
            outlined
            dense
            clearable
            :hide-details="true"
            class="mb-3"
            prepend-inner-icon="mdi-magnify"
            @keyup.enter="search"
            @click:clear="clearSearch"
          />

          <div class="eb-book-list">
            <div v-if="searching" class="text-center py-6">
              <v-progress-circular indeterminate color="primary" size="32" />
            </div>
            <div v-else-if="books.length === 0 && searched" class="text-center py-4 grey--text">
              {{ $t('epubBeautify.noResults') }}
            </div>
            <v-list v-else-if="books.length > 0" dense class="eb-list pa-0">
              <v-list-item
                v-for="book in books"
                :key="book.id"
                :class="['eb-book-item', { 'eb-book-selected': selected && selected.id === book.id }]"
                @click="selectBook(book)"
              >
                <v-list-item-action class="mr-2 my-0" @click.stop>
                  <v-checkbox
                    :input-value="batchIds.includes(book.id)"
                    dense hide-details class="mt-0 pt-0"
                    @change="togBatch(book.id)"
                  />
                </v-list-item-action>
                <v-list-item-avatar tile size="44" class="mr-3">
                  <v-img :src="book.thumb" :alt="book.title">
                    <template #error>
                      <v-icon color="grey lighten-1">mdi-book-outline</v-icon>
                    </template>
                  </v-img>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title class="eb-book-title">{{ book.title }}</v-list-item-title>
                  <v-list-item-subtitle class="eb-book-author">{{ (book.authors || []).join(', ') }}</v-list-item-subtitle>
                  <div class="mt-1">
                    <v-chip
                      v-for="(file, idx) in (book.files || [])"
                      :key="file.format + '_' + idx"
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

          <!-- 分析结果 / 体检报告 -->
          <template v-if="selected">
            <v-alert v-if="analysisError" type="error" dense text rounded class="mb-0 mt-3">{{ analysisError }}</v-alert>
            <div v-else-if="analysis" class="eb-health mt-3">
              <div class="eb-health-head" @click="healthOpen = !healthOpen">
                <v-icon small class="mr-1" :class="{ 'eb-arr-open': healthOpen }">mdi-chevron-right</v-icon>
                {{ $t('epubBeautify.healthTitle') }}
              </div>
              <v-expand-transition>
                <div v-show="healthOpen" class="pt-2">
                  <div class="d-flex flex-wrap">
                    <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisChapters', { count: analysis.text_entries }) }}</v-chip>
                    <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisToc', { kind: tocKindText }) }}</v-chip>
                    <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisFonts', { has: analysis.has_fontface ? $t('epubBeautify.yes') : $t('epubBeautify.no') }) }}</v-chip>
                    <v-chip v-if="analysis.calibre_soup" x-small outlined color="warning" class="mr-2 mb-1">{{ $t('epubBeautify.analysisCalibre') }}</v-chip>
                    <v-chip x-small outlined class="mr-2 mb-1">{{ $t('epubBeautify.analysisHeadings', { count: headingCount }) }}</v-chip>
                    <v-chip v-if="analysis.leading_space_paras" x-small outlined color="secondary" class="mr-2 mb-1">{{ $t('epubBeautify.anaLeading', { count: analysis.leading_space_paras }) }}</v-chip>
                    <v-chip v-if="analysis.empty_para_est" x-small outlined color="secondary" class="mr-2 mb-1">{{ $t('epubBeautify.anaEmpty', { count: analysis.empty_para_est }) }}</v-chip>
                    <v-chip v-if="analysis.p_close_mismatch_files" x-small outlined color="error" class="mr-2 mb-1">{{ $t('epubBeautify.anaMismatch', { count: analysis.p_close_mismatch_files }) }}</v-chip>
                    <v-chip v-if="analysis.css_conflict_risk" x-small outlined color="warning" class="mr-2 mb-1">{{ $t('epubBeautify.anaConflict', { count: analysis.css_important_count }) }}</v-chip>
                    <v-chip v-if="analysis.image_count" x-small outlined class="mb-1">{{ $t('epubBeautify.anaImages', { count: analysis.image_count, big: analysis.image_oversize || 0 }) }}</v-chip>
                    <v-chip v-if="analysis.dialogue_paras" x-small outlined color="secondary" class="mr-2 mb-1">{{ $t('epubBeautify.anaDialogue', { count: analysis.dialogue_paras }) }}</v-chip>
                    <v-chip v-if="analysis.notes_refs" x-small outlined color="secondary" class="mr-2 mb-1">{{ $t('epubBeautify.anaNotes', { count: analysis.notes_refs }) }}</v-chip>
                  </div>
                  <div v-if="tocPreviewText" class="mt-2 caption grey--text eb-toc-preview">
                    <div class="font-weight-medium">{{ $t('epubBeautify.tocPreviewTitle') }}</div>
                    <div style="max-height:96px;overflow-y:auto;white-space:pre-line">{{ tocPreviewText }}</div>
                  </div>
                </div>
              </v-expand-transition>
            </div>
          </template>
        </v-card>

        <!-- ─── ② 挑风格 ─── -->
        <v-card outlined class="eb-card mb-4 pa-5 rounded-lg">
          <div class="d-flex align-center mb-3">
            <span class="eb-stepnum mr-2">2</span>
            <span class="text-subtitle-1 font-weight-bold">{{ $t('epubBeautify.presetTitle') }}</span>
            <span class="caption grey--text ml-2">{{ $t('epubBeautify.previewHint') }}</span>
          </div>

          <div class="eb-pgrid mb-2">
            <div
              v-for="p in presets"
              :key="p.id"
              :class="['eb-pcard', { 'eb-pcard-selected': preset === p.id }]"
              :style="{ '--pa': (p.accent || '#1976d2') }"
              @click="preset = p.id"
            >
              <div class="body-2 font-weight-bold d-flex align-center">
                {{ $i18n.locale === 'en' ? p.name_en : p.name }}
                <span v-if="p.page_progression === 'rtl'" class="eb-rtlb">{{ $t('epubBeautify.rtlBadge') }}</span>
              </div>
              <div class="eb-mini mt-1" :style="miniStyle(p)">
                <span>{{ $i18n.locale === 'en' ? p.name_en : p.name }}</span>
              </div>
              <div class="caption grey--text eb-scene mt-1">{{ p.scene }}</div>
              <div class="d-flex mt-1">
                <span class="eb-swatch" :style="{ background: p.accent }" />
                <span class="eb-swatch eb-swatch-b" :style="{ background: p.quote_bg }" />
                <span class="eb-swatch eb-swatch-b" :style="{ background: p.accent_light }" />
                <span class="eb-swatch" :style="{ background: p.border }" />
              </div>
            </div>
          </div>

          <div class="text-subtitle-2 font-weight-medium mb-1 mt-3">{{ $t('epubBeautify.tocStyleTitle') }}</div>
          <v-row dense>
            <v-col v-for="ts in tocStyles" :key="ts.id" cols="6" sm="3" class="mb-1">
              <v-card
                outlined
                rounded
                :class="['eb-preset', { 'eb-preset-selected': tocStyle === ts.id }]"
                @click="tocStyle = ts.id"
              >
                <v-card-text class="pa-2">
                  <div class="caption font-weight-medium d-flex align-center">
                    <v-icon v-if="tocStyle === ts.id" x-small color="primary" class="mr-1">mdi-check-circle</v-icon>
                    {{ $i18n.locale === 'en' ? ts.name_en : ts.name }}
                  </div>
                  <div class="eb-toc-mini mt-1" :style="tocMiniFrame(ts.id)">
                    <div v-if="ts.id === 'cool'" class="eb-toc-mock" :style="{ backgroundColor: currentPreset.accent, backgroundImage: currentPreset.toc_gradient, color: '#F5E6D0', borderBottom: '1px solid #C9A96A' }">目 录</div>
                    <div v-else-if="ts.id === 'minimal'" class="eb-toc-mock" :style="{ background: 'transparent', color: currentPreset.accent, letterSpacing: '0.3em', fontSize: '0.72rem', fontWeight: 600 }">目 录</div>
                    <div v-else class="eb-toc-mock" :style="{ background: ts.id === 'seal' ? '#FFFFFF' : currentPreset.accent_light, color: currentPreset.accent, borderTop: ts.id === 'elegant' ? ('2px solid ' + currentPreset.accent) : 'none', textAlign: ts.id === 'seal' ? 'left' : 'center' }">目 录<span v-if="ts.id === 'seal'" style="background:#B54942;color:#F5E6D0;font-size:0.6em;padding:0 3px;border-radius:2px;margin-left:4px">隐</span></div>
                    <div class="eb-toc-row" :style="ts.id === 'minimal' ? { borderBottom: 'none' } : {}"><span :style="{ color: ts.id === 'minimal' ? (currentPreset.muted || '#999') : currentPreset.accent, fontWeight: ts.id === 'minimal' ? 400 : 700 }">01</span>第一章 示例标题</div>
                    <div class="eb-toc-row" :style="{ borderBottom: 'none' }"><span :style="{ color: ts.id === 'minimal' ? (currentPreset.muted || '#999') : currentPreset.accent, fontWeight: ts.id === 'minimal' ? 400 : 700 }">02</span>第二章 示例标题<template v-if="ts.id === 'seal'"><span style="float:right;color:#A2906A">\ ✦</span></template></div>
                  </div>
                </v-card-text>
              </v-card>
            </v-col>
          </v-row>
        </v-card>

        <!-- ─── ③ 微调选项（默认收起） ─── -->
        <v-expansion-panels flat class="eb-panels" style="border:1px solid #e0e0e0">
          <v-expansion-panel>
            <v-expansion-panel-header class="eb-tune-head">
              <div class="d-flex align-center min-width-0">
                <span class="eb-stepnum eb-stepnum-alt mr-2">3</span>
                <span class="text-subtitle-1 font-weight-bold">{{ $t('epubBeautify.tuneTitle') }}</span>
                <v-chip x-small class="ml-3 eb-dsum grey--text text--darken-1">{{ tuneSummary }}</v-chip>
              </div>
            </v-expansion-panel-header>
            <v-expansion-panel-content class="pt-2">

              <!-- 字体排版：三态分段，仅第三档展开分档开关 -->
              <div class="eb-grp">
                <div class="text-subtitle-2 font-weight-medium mb-2">{{ $t('epubBeautify.grpFonts') }}</div>
                <v-btn-toggle v-model="fontMode" mandatory dense class="mb-1">
                  <v-btn small value="sys">{{ $t('epubBeautify.fontModeSys') }}</v-btn>
                  <v-btn small value="orig">{{ $t('epubBeautify.fontModeOrig') }}</v-btn>
                  <v-btn small value="mix">{{ $t('epubBeautify.fontModeMix') }}</v-btn>
                </v-btn-toggle>
                <div v-if="fontMode === 'mix'" class="d-flex flex-wrap mt-1">
                  <span :class="['eb-fpill', { 'on': fontBody }]" @click="fontBody = !fontBody">{{ $t('epubBeautify.fontBody') }}</span>
                  <span :class="['eb-fpill', { 'on': fontHead }]" @click="fontHead = !fontHead">{{ $t('epubBeautify.fontHead') }}</span>
                  <span :class="['eb-fpill', { 'on': fontKai }]" @click="fontKai = !fontKai">{{ $t('epubBeautify.fontKai') }}</span>
                  <span :class="['eb-fpill', { 'on': fontCode }]" @click="fontCode = !fontCode">{{ $t('epubBeautify.fontCode') }}</span>
                </div>
                <div class="eb-crow mt-1">
                  <v-switch v-model="titleSplit" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.titleSplitEnable') }}</div>
                    <div class="caption grey--text">{{ $t('epubBeautify.titleSplitDesc') }}</div>
                  </div>
                </div>
              </div>

              <!-- 段落排版：首行缩进独立开关 + 段间距可调 -->
              <div class="eb-grp">
                <div class="text-subtitle-2 font-weight-medium mb-1">{{ $t('epubBeautify.paraModeTitle') }}</div>
                <div class="eb-crow">
                  <v-switch v-model="paraIndent" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.paraIndentLabel') }}</div>
                    <div class="caption grey--text">{{ $t('epubBeautify.paraIndentDesc') }}</div>
                  </div>
                </div>
                <div class="d-flex align-center mt-1">
                  <span class="body-2 mr-4" style="min-width:56px">{{ $t('epubBeautify.paraGapLabel') }}</span>
                  <v-slider
                    v-model="paraGap"
                    :min="0"
                    :max="1.5"
                    :step="0.05"
                    thumb-label="always"
                    hide-details
                    class="mt-0 pt-0"
                    style="max-width:230px"
                  />
                  <span class="caption grey--text ml-3">em</span>
                </div>
                <div class="caption grey--text mt-n2">{{ paraGapText }}</div>
              </div>

              <!-- 内容清理：联动体检推荐 -->
              <div class="eb-grp">
                <div class="text-subtitle-2 font-weight-medium mb-1 d-flex align-center">
                  {{ $t('epubBeautify.cleanTitle') }}
                  <span class="eb-count ml-2">{{ cleanCount }}/3</span>
                </div>
                <div class="eb-crow">
                  <v-switch v-model="cleanLeading" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.cleanLeading') }}<span v-if="recs.leading" class="eb-recb ml-1">{{ $t('epubBeautify.recBadge') }}</span></div>
                    <div class="caption grey--text">{{ cleanLeadingDesc }}</div>
                  </div>
                </div>
                <div class="eb-crow">
                  <v-switch v-model="cleanEmpty" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.cleanEmpty') }}<span v-if="recs.empty" class="eb-recb ml-1">{{ $t('epubBeautify.recBadge') }}</span></div>
                    <div class="caption grey--text">{{ cleanEmptyDesc }}</div>
                  </div>
                </div>
                <div class="eb-crow">
                  <v-switch v-model="cleanMeta" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.cleanMeta') }}<span v-if="recs.meta" class="eb-recb ml-1">{{ $t('epubBeautify.recBadge') }}</span></div>
                    <div class="caption grey--text">{{ cleanMetaDesc }}</div>
                  </div>
                </div>
              </div>

        <!-- 对话行点缀 -->
        <div class="eb-grp">
          <div class="text-subtitle-2 font-weight-medium mb-1">{{ $t('epubBeautify.dialogueTitle') }}</div>
          <div class="eb-crow">
            <v-switch v-model="dialogue" dense hide-details class="mt-0 pt-0" />
            <div class="min-width-0">
              <div class="body-2">{{ $t('epubBeautify.dialogueEnable') }}</div>
              <div class="caption grey--text">{{ dialogueHint }}</div>
            </div>
          </div>
        </div>

        <!-- 弹注/标注 -->
        <div class="eb-grp">
          <div class="text-subtitle-2 font-weight-medium mb-1">{{ $t('epubBeautify.notesTitle') }}</div>
          <div class="eb-crow">
            <v-switch v-model="notesOn" dense hide-details class="mt-0 pt-0" />
            <div class="min-width-0">
              <div class="body-2">{{ $t('epubBeautify.notesEnable') }}<span v-if="notesRec" class="eb-recb ml-1">{{ $t('epubBeautify.recBadge') }}</span></div>
              <div class="caption grey--text">{{ notesHint }}</div>
            </div>
          </div>
          <v-expand-transition>
            <div v-if="notesOn" class="d-flex align-center ml-6 mt-1">
              <span class="body-2 mr-3" style="min-width:64px">{{ $t('epubBeautify.noteMarkLabel') }}</span>
              <v-select
                v-model="noteMark"
                :items="noteMarkItems"
                item-text="label"
                item-value="value"
                dense hide-details
                style="max-width:210px"
                class="mt-0"
              />
              <sup class="ml-3" :style="{color: currentPreset.accent, fontWeight: 700}">{{ markGlyph }}</sup>
            </div>
          </v-expand-transition>
        </div>

              <!-- 目录层级 + 双栏 + 全书底色 -->
              <div class="eb-grp">
                <div class="d-flex align-center flex-wrap">
                  <span class="text-subtitle-2 font-weight-medium mr-3">{{ $t('epubBeautify.tocDepth') }}</span>
                  <v-select
                    v-model="tocDepth"
                    :items="depthItems"
                    item-text="label"
                    item-value="value"
                    dense hide-details
                    style="max-width:160px"
                    class="mt-0"
                  />
                  <v-switch
                    v-model="tocColumns"
                    :label="$t('epubBeautify.tocColumns')"
                    dense hide-details
                    class="mt-0 pt-0 ml-6"
                  />
                </div>
                <div class="caption grey--text mt-n1">{{ $t('epubBeautify.tocColumnsDesc') }}</div>
                <div class="d-flex align-center flex-wrap mt-3">
                  <span class="text-subtitle-2 font-weight-medium mr-3">{{ $t('epubBeautify.pageTintTitle') }}</span>
                  <v-btn-toggle v-model="pageTint" mandatory dense>
                    <v-btn small value="auto">{{ $t('epubBeautify.pageTintAuto') }}</v-btn>
                    <v-btn small value="on">{{ $t('epubBeautify.pageTintOn') }}</v-btn>
                    <v-btn small value="off">{{ $t('epubBeautify.pageTintOff') }}</v-btn>
                  </v-btn-toggle>
                </div>
              </div>

              <!-- 自定义配色 -->
              <div class="eb-grp">
                <div class="text-subtitle-2 font-weight-medium mb-1">{{ $t('epubBeautify.paletteTitle') }}</div>
                <v-switch v-model="paletteOn" :label="$t('epubBeautify.paletteEnable')" dense hide-details class="mt-0" />
                <v-expand-transition>
                  <div v-if="paletteOn" class="d-flex flex-wrap align-end ml-6 mt-1">
                    <div class="mr-6 text-center">
                      <div class="caption mb-1">{{ $t('epubBeautify.paletteAccent') }}</div>
                      <v-color-picker
                        v-model="palAccent"
                        mode="hex" hide-mode-switch hide-inputs
                        width="120" flat
                        @update:color="palTouched.accent = true"
                      ></v-color-picker>
                    </div>
                    <div class="text-center">
                      <div class="caption mb-1">{{ $t('epubBeautify.paletteBg') }}</div>
                      <v-color-picker
                        v-model="palBg"
                        mode="hex" hide-mode-switch hide-inputs
                        width="120" flat
                        @update:color="palTouched.bg = true"
                      ></v-color-picker>
                    </div>
                  </div>
                </v-expand-transition>
                <div class="caption grey--text mt-1">{{ $t('epubBeautify.paletteHint') }}</div>
              </div>

              <!-- 背景图片 -->
              <div class="eb-grp">
                <div class="grp-t">{{ $t('epubBeautify.bgTitle') }}</div>
                <div class="d-flex align-center flex-wrap">
                  <v-btn small outlined :loading="bgLoading" @click="triggerBgUpload">
                    <v-icon small left>mdi-image-plus</v-icon>{{ $t('epubBeautify.bgUpload') }}
                  </v-btn>
                  <input ref="bgFile" type="file" accept=".jpg,.jpeg,.png,.webp,image/*" style="display:none" @change="onBgFile">
                  <span class="caption grey--text mx-2">{{ $t('epubBeautify.bgTexture') }}</span>
                  <span
                    v-for="t in textures"
                    :key="t.id"
                    :class="['eb-tex', 'eb-tex-' + t.id]"
                    :title="t.name"
                    @click="pickBuiltin(t.id)"
                  ></span>
                  <template v-if="bgHas && bgObjectUrl">
                    <img :src="bgObjectUrl" class="eb-bgpick" alt="">
                    <v-btn small text color="error" class="ml-1" @click="delBg">{{ $t('epubBeautify.bgDelete') }}</v-btn>
                  </template>
                  <span v-else-if="!bgHas" class="caption grey--text ml-2">{{ $t('epubBeautify.bgNone') }}</span>
                </div>
                <div class="eb-crow mt-1">
                  <v-switch v-model="bgOn" :disabled="!bgHas" dense hide-details class="mt-0 pt-0" />
                  <div class="min-width-0">
                    <div class="body-2">{{ $t('epubBeautify.bgEnable') }}</div>
                    <div class="caption grey--text">{{ $t('epubBeautify.bgEnableDesc') }}</div>
                  </div>
                </div>
              </div>

              <!-- 新书命名 -->
              <div class="eb-grp">
                <v-text-field
                  v-model="suffix"
                  :label="$t('epubBeautify.suffix')"
                  outlined
                  dense
                  maxlength="30"
                  :counter="30"
                  prepend-inner-icon="mdi-format-title"
                />
              </div>

            </v-expansion-panel-content>
          </v-expansion-panel>
        </v-expansion-panels>
      </v-col>

      <!-- ═══ 右栏：实时预览 ═══ -->
      <v-col cols="12" lg="5" class="pt-0">
        <div class="eb-previewcol">
          <v-btn-toggle v-model="previewTab" mandatory dense class="eb-ptabs mb-3">
            <v-btn small value="ch">{{ $t('epubBeautify.previewBodyTab') }}</v-btn>
            <v-btn small value="toc">{{ $t('epubBeautify.previewTocTab') }}</v-btn>
            <v-btn small value="orig">{{ $t('epubBeautify.previewOrigTab') }}</v-btn>
          </v-btn-toggle>

          <div class="eb-phone">
            <div class="eb-notch"></div>
            <div class="eb-screen" :style="screenStyleObj">
              <template v-if="!selected">
                <div class="eb-empty-tip">
                  {{ $t('epubBeautify.previewIdleTitle') }}<br>
                  <span class="caption">{{ $t('epubBeautify.previewIdleSub') }}</span>
                </div>
              </template>
                <template v-else-if="previewTab === 'ch'">
                <!-- 竖排古籍：整体竖排渲染（titleSplit 亦生效） -->
                <div v-if="currentPreset.id === 'vertclassical'" class="eb-vpad">
                  <div class="eb-vbody" :style="{ background: currentPreset.accent_light, borderLeftColor: currentPreset.border, borderRightColor: currentPreset.border, fontFamily: bodyFont }">
                    <div class="eb-vtitle" :style="{ color: currentPreset.accent, fontFamily: kaiFont }"><template v-if="titleSplit && splitSample"><span style="display:block;font-size:0.6em;opacity:0.7;letter-spacing:0.2em">{{ splitSample[0] }}</span>{{ splitSample[1] }}</template><template v-else>{{ chapterSample }}</template></div>
                    <div>{{ chapterParas[0] }}</div>
                    <div>{{ chapterParas[1] }}</div>
                  </div>
                  <div class="eb-vnote">← {{ $t('epubBeautify.verticalNote') }}</div>
                </div>
                <div v-else>
                  <!-- 章节标题：按预设特例渲染（titleSplit 对三特例亦生效） -->
                  <div v-if="currentPreset.id === 'inkstone'" class="eb-t-ink" :style="{ background: currentPreset.accent, fontFamily: headFont }"><template v-if="titleSplit && splitSample"><span class="eb-t-num" style="display:block;font-size:0.55em;opacity:0.85;letter-spacing:0.35em;margin-bottom:2px">{{ splitSample[0] }}</span><span class="eb-t-title">{{ splitSample[1] }}</span></template><template v-else>{{ chapterSample }}</template></div>
                  <div v-else-if="currentPreset.id === 'xuanzhi'" class="eb-t-xz-wrap">
                    <div class="eb-t-xz-title" :style="{ color: currentPreset.accent, fontFamily: headFont }"><template v-if="titleSplit && splitSample"><span class="eb-t-num" style="display:block;font-size:0.55em;opacity:0.7;letter-spacing:0.3em;margin-bottom:4px">{{ splitSample[0] }}</span><span class="eb-t-title">{{ splitSample[1] }}</span></template><template v-else>{{ chapterSample }}</template></div>
                    <div class="eb-t-xz-bar mx-auto" :style="{ background: currentPreset.accent }"></div>
                  </div>
                  <div v-else-if="currentPreset.id === 'modern'" class="eb-t-leftbar" :style="{ color: currentPreset.accent, borderLeftColor: currentPreset.accent, fontFamily: headFont }"><template v-if="titleSplit && splitSample"><span class="eb-t-num" style="display:block;font-size:0.6em;opacity:0.7;letter-spacing:0.3em;margin-bottom:2px">{{ splitSample[0] }}</span><span class="eb-t-title">{{ splitSample[1] }}</span></template><template v-else>{{ chapterSample }}</template></div>
                  <div v-else class="eb-t-card" :class="{ 'eb-round': currentPreset.id === 'children' }" :style="{ background: currentPreset.accent_light, color: currentPreset.accent, borderTopColor: currentPreset.accent, borderBottomColor: currentPreset.border, fontFamily: headFont }"><template v-if="titleSplit && splitSample"><span class="eb-t-num">{{ splitSample[0] }}</span><span class="eb-t-title">{{ splitSample[1] }}</span></template><template v-else>{{ chapterSample }}</template></div>

                  <!-- 标题下长线 -->
                  <div v-if="currentPreset.id === 'classical'" class="eb-sep-dbl" :style="{ borderTopColor: currentPreset.accent, borderBottomColor: hexA(currentPreset.accent, 0.45) }"></div>
                  <div v-else class="eb-sep" :style="{ background: gradLine(currentPreset.accent) }"></div>

                  <!-- 正文（书内真实段落，未命中回落示例；缩进/段距实时联动） -->
                  <p :class="['eb-p', paraIndent ? 'eb-indent' : 'eb-spacing']" :style="paraPStyle">{{ chapterParas[0] }}</p>
                  <p :class="['eb-p', paraIndent ? 'eb-indent' : 'eb-spacing']" :style="paraPStyle">{{ chapterParas[1] }}</p>
                  <p v-if="dialogue" class="eb-p eb-dialog-demo" :class="{ 'eb-spacing': !paraIndent }" :style="dialogueStyle">{{ dialogDemoText }}</p>
                  <p :class="['eb-p', paraIndent ? 'eb-indent' : 'eb-spacing']" :style="paraPStyle">{{ chapterParas[2] }}<sup v-if="notesOn" :style="{color: currentPreset.accent, fontWeight: 700, fontSize: '0.78em'}"> {{ markGlyph }}</sup></p>
                  <!-- 弹注注释卡预览（章末/弹出内容样式） -->
                  <div v-if="notesOn" :style="{background: currentPreset.quote_bg, borderLeft: '3px solid ' + currentPreset.accent, borderRadius: '3px', padding: '7px 9px', marginTop: '14px'}">
                    <div class="caption" :style="{fontFamily: kaiFont, color: '#666', lineHeight: 1.6}"><span :style="{color: currentPreset.muted}">{{ markGlyph }}</span> {{ $t('epubBeautify.notesPreviewLine') }}</div>
                  </div>
                  <!-- 引文样式演示（保留但标“演示”并置末，避免全书误为正文） -->
                  <blockquote class="eb-quote" :style="{ background: currentPreset.quote_bg, borderLeftColor: currentPreset.accent, color: currentPreset.muted, fontFamily: kaiFont, borderRadius: currentPreset.id === 'children' ? '8px' : '3px', marginTop: '16px' }">「满纸荒唐言，一把辛酸泪。都云作者痴，谁解其中味。」<span class="caption grey--text ml-2" style="font-size:10px; vertical-align:middle;">{{ $t('epubBeautify.demoTag') }}</span></blockquote>
                </div>
              </template>
              <template v-else-if="previewTab === 'toc'">
                <!-- 目录预览：按目录形式渲染（tocIsMock 时标“示例”） -->
                <div class="eb-tocbig" :class="{ 'eb-toc-cols': tocColumns && tocStyle !== 'seal' }">
                  <div v-if="tocIsMock" class="caption grey--text text-center mb-2">{{ $t('epubBeautify.tocMockHint') }}</div>
                  <div v-if="tocStyle === 'elegant'" class="eb-toc-frame" :style="{ borderColor: currentPreset.border }">
                    <div class="eb-th-elegant" :style="{ background: currentPreset.accent_light, borderTopColor: currentPreset.accent, color: currentPreset.accent }">目 录<div class="eb-th-sub" :style="{ color: currentPreset.muted }">CONTENTS</div></div>
                    <div v-for="(r, i) in tocSampleRowsDisplay" :key="i" class="eb-tr" :style="{ borderBottomColor: currentPreset.border }">
                      <span class="eb-num-badge" :style="{ background: currentPreset.accent_light, color: currentPreset.accent }">{{ r[0] }}</span><span class="eb-rt">{{ r[1] }}</span>
                    </div>
                    <div class="text-center py-2" :style="{ color: currentPreset.accent, fontSize: '11px' }">◆</div>
                  </div>
                  <div v-else-if="tocStyle === 'cool'" class="eb-toc-frame" :style="{ borderColor: currentPreset.border }">
                    <div class="eb-cool-head" :style="{ background: currentPreset.toc_gradient || currentPreset.accent }">目 录<div class="eb-th-sub">CONTENTS</div></div>
                    <div class="eb-cool-items" :style="{ borderLeftColor: currentPreset.accent, background: currentPreset.quote_bg }">
                      <div v-for="(r, i) in tocSampleRowsDisplay" :key="i" class="eb-cool-row" :style="{ borderBottomColor: currentPreset.border }">
                        <span :style="{ color: currentPreset.accent, fontWeight: 800, fontSize: '14px', minWidth: '24px' }">{{ r[0] }}</span><span class="eb-rt">{{ r[1] }}</span>
                      </div>
                    </div>
                  </div>
                  <div v-else-if="tocStyle === 'seal'" class="eb-seal-frame">
                    <div class="eb-seal-head" :style="{ borderBottomColor: currentPreset.border }">
                      <span class="eb-seal-title" :style="{ color: currentPreset.accent }">目 录</span>
                      <span class="eb-seal-stamp">隐</span>
                    </div>
                    <div v-for="(r, i) in tocSampleRowsDisplay" :key="i" class="eb-seal-row">
                      <span :style="{ color: currentPreset.accent, fontWeight: 700, fontSize: '12px' }">{{ r[0] }}</span>
                      <span class="flex-grow-1 eb-rt">{{ r[1] }}</span>
                      <span style="color:#A2906A;font-size:11px">\ ✦</span>
                    </div>
                    <div v-if="tocColumns" class="caption grey--text text-center mt-2">{{ $t('epubBeautify.sealNoColumns') }}</div>
                  </div>
                  <div v-else class="eb-min-frame">
                    <div class="eb-min-head" :style="{ color: currentPreset.accent }">目 录</div>
                    <div v-for="(r, i) in tocSampleRowsDisplay" :key="i" class="eb-min-row">
                      <span :style="{ color: currentPreset.muted, minWidth: '18px', fontSize: '12px' }">{{ r[0] }}</span><span class="eb-rt">{{ r[1] }}</span>
                    </div>
                    <div class="eb-min-end" :style="{ borderTopColor: currentPreset.border }"></div>
                  </div>
                </div>
              </template>
              <template v-else-if="previewTab === 'orig'">
                <!-- 原书效果：无样式裸渲染，用于对比 -->
                <div style="padding: 6px 4px; font-family: Georgia, 'Times New Roman', 宋体, serif; line-height: 1.85; color: #222; font-size: 15px">
                  <h2 style="text-align: center; margin: 0 0 18px; font-size: 17px">{{ chapterSample }}</h2>
                  <p style="margin: 0 0 14px; text-indent: 2em">{{ chapterParas[0] }}</p>
                  <p style="margin: 0 0 14px; text-indent: 2em">{{ chapterParas[1] }}</p>
                  <p style="margin: 0 0 14px; text-indent: 2em">{{ dialogDemoText }}</p>
                </div>
              </template>
              <div v-if="selected" class="eb-screen-end grey--text">— {{ $t('epubBeautify.chapterEnd') }} —</div>
            </div>
          </div>
          <div class="caption grey--text text-center mt-2">{{ $t('epubBeautify.previewNote') }}</div>
        </div>
      </v-col>
    </v-row>

    <!-- ═══ 底部粘性操作栏 ═══ -->
    <div class="eb-actionbar">
      <div class="eb-bar-in">
        <template v-if="processing">
          <div class="flex-grow-1 mr-2" style="min-width:220px">
            <v-progress-linear :value="progress" color="primary" height="8" rounded class="mb-1" />
            <div class="text-center caption grey--text">{{ progressMsg }}</div>
          </div>
        </template>
        <template v-else-if="resultMsg">
          <div class="flex-grow-1">
            <v-alert dense :type="resultType === 'success' ? 'success' : resultType === 'warning' ? 'warning' : 'error'" text class="mb-0 py-1">
              {{ resultMsg }}
            </v-alert>
            <div v-if="resultDetails.length" class="mt-1">
              <div v-for="r in resultDetails" :key="r.book_id" class="caption red--text">{{ $t('epubBeautify.batchFail', { id: r.book_id, err: r.error || '' }) }}</div>
            </div>
          </div>
          <v-btn
            v-if="resultType === 'success' && newBookId"
            small
            outlined
            color="primary"
            @click="$router.push('/book/' + newBookId)"
          >
            <v-icon small left>mdi-book-open-page-variant</v-icon>{{ $t('epubBeautify.viewBook') }}
          </v-btn>
        </template>
        <template v-else>
          <v-chip v-if="!selected && !batchIds.length" small class="eb-schip eb-schip-mut">{{ $t('epubBeautify.noBookChip') }}</v-chip>
          <template v-else>
            <v-chip v-if="selected" small class="eb-schip"><strong class="mr-1">{{ selected.title }}</strong></v-chip>
            <v-chip small class="eb-schip"><span class="eb-dot mr-1" :style="{ background: currentPreset.accent }"></span>{{ currentPresetName }}</v-chip>
            <v-chip small class="eb-schip">{{ tocStyleName }}{{ $t('epubBeautify.tocChip') }}</v-chip>
            <v-chip v-if="batchIds.length" small class="eb-schip eb-schip-batch">{{ $t('epubBeautify.batchQueued') }} {{ batchIds.length }}</v-chip>
          </template>
        </template>
        <v-spacer></v-spacer>
        <v-btn
          v-if="!processing"
          large
          color="primary"
          :disabled="((!selected || analysisError !== '') && !batchIds.length)"
          @click="startRun"
        >
          <v-icon left>mdi-play</v-icon>{{ runBtnLabel }}
        </v-btn>
      </div>
    </div>
  </v-container>
</template>

<script>
const ORIG_FONT = '"Georgia","Times New Roman","宋体","SimSun",serif';
const SYS_BODY_FONT = '"Noto Serif SC","Source Han Serif SC","思源宋体","宋体","Songti SC","STSong",serif';
const SYS_HEAD_FONT = '"Noto Sans SC","Source Han Sans SC","思源黑体","黑体","PingFang SC","Microsoft YaHei",sans-serif';
const SYS_KAI_FONT = '"Kaiti SC","楷体","STKaiti","KaiTi",serif';

export default {
  data: () => ({
    query: '',
    books: [],
    searching: false,
    searched: false,
    selected: null,

    analysis: null,
    analysisError: '',
    presets: [],

    preset: 'classic',
    tocStyle: 'elegant',
    tocStyles: [
      { id: 'elegant', name: '精致', name_en: 'Elegant' },
      { id: 'cool', name: '酷炫', name_en: 'Cool' },
      { id: 'seal', name: '朱印', name_en: 'Seal' },
      { id: 'minimal', name: '极简', name_en: 'Minimal' },
    ],
    // 字体三态：sys 统一系统字体 / orig 保留原书 / mix 分档自定义
    fontMode: 'sys',
    fontBody: true,
    fontHead: true,
    fontKai: true,
    fontCode: true,
    // 内容清理（选中书籍后按体检推荐自动勾选）
    cleanLeading: true,
    cleanEmpty: false,
    cleanMeta: true,
    // 对话行点缀（默认关）
    dialogue: false,
    // 弹注/标注（默认开：纯样式增强 + B 型语义归一化，可一键关闭回退）
    notesOn: true,
    noteMark: 'orig',
    // 双行排版（默认关）
    titleSplit: false,
    // 段落排版：首行缩进独立开关 + 段间距数值（em，0=跟随预设）
    paraIndent: true,
    paraGap: 0,
    // 目录双栏（默认关，仅生成的目录页）
    tocColumns: false,
    // 批量队列（勾选入队的书籍 ID）
    batchIds: [],
    // 背景图片（全局复用一张，默认关）
    bgOn: false,
    bgHas: false,
    bgLoading: false,
    bgObjectUrl: '',
    textures: [
      { id: 'xuanzhi', name: '宣纸纹' },
      { id: 'parchment', name: '羊皮纸' },
      { id: 'linen', name: '素麻布' },
    ],
    // 目录深度（0 = 全部）
    tocDepth: 0,
    // 全书底色与自定义配色
    pageTint: 'auto',
    paletteOn: false,
    palAccent: '',
    palBg: '',
    palTouched: { accent: false, bg: false },
    suffix: '',

    // 实时预览
    previewTab: 'ch',
    healthOpen: true,
    tocMockRows: [
      ['01', '第一章 示例标题'],
      ['02', '第二章 示例标题'],
      ['03', '第三章 示例标题'],
      ['04', '第四章 示例标题'],
      ['05', '第五章 示例标题'],
    ],

    processing: false,
    progress: 0,
    progressMsg: '',
    resultMsg: '',
    resultType: 'success',
    newBookId: null,
    resultDetails: [],
    pollTimer: null,
    pollNotFound: 0,
    previewSeq: 0,
    searchDebounce: null,
  }),
  computed: {
    tocKindText() {
      if (!this.analysis) return '';
      if (this.analysis.has_inbook_toc) return this.$t('epubBeautify.tocInbook');
      if (this.analysis.ncx_entries > 0) return this.$t('epubBeautify.tocNcx');
      if (this.analysis.nav_entries > 0) return this.$t('epubBeautify.tocNav');
      return this.$t('epubBeautify.tocNone');
    },
    headingCount() {
      if (!this.analysis) return 0;
      const s = this.analysis.heading_stats || {};
      // 与后端 analyze 口径一致：h1-h6 全量 + 段落文本识别数
      return ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].reduce((n, k) => n + (s[k] || 0), 0) + this.analysis.text_headings;
    },
    tocPreviewText() {
      const titles = (this.analysis && this.analysis.toc_preview_titles) || [];
      return titles.map((t, i) => (i + 1) + '. ' + t).join('\n');
    },
    chapterSample() {
      // 优先用首章真实标题（正文识别命中），其次目录预览标题，最后通用示例（不派生书名，避免误为真实目录）
      const pc = this.analysis && this.analysis.preview_chapter;
      if (pc && pc.title) return pc.title;
      const t = this.analysis && this.analysis.toc_preview_titles;
      if (t && t[0]) return t[0];
      return '第一章 示例标题';
    },
    // 首章真实段落（≤3）；不足或未命中时回落示例文案
    chapterParas() {
      const MOCKS = [
        '天色将明未明，山道上薄雾未散，一行脚印自东而来，又消失在石桥尽头。',
        '青砖黛瓦的宅院静静卧在雾里，檐角铜铃偶尔轻响一声，像是在应和着远处更夫懒散的梆子声。',
        '他攥紧了手中的包袱，加快脚步走进雾中。',
      ];
      const real = (this.analysis && this.analysis.preview_chapter && this.analysis.preview_chapter.paragraphs) || [];
      return [0, 1, 2].map((i) => real[i] || MOCKS[i]);
    },
    // 对话演示行：真实段落中以开引号起始者优先
    dialogDemoText() {
      const real = (this.analysis && this.analysis.preview_chapter && this.analysis.preview_chapter.paragraphs) || [];
      const hit = real.find((t) => t && '「『“＂'.indexOf(t[0]) >= 0);
      return hit || '「你终于来了。」他压低了声音。';
    },
    paraGapText() {
      return this.paraGap > 0
        ? this.$t('epubBeautify.paraGapOn', { n: this.paraGap.toFixed(2) })
        : this.$t('epubBeautify.paraGapOff');
    },
    // 正文段样式：字体/行高 + 自定义段距
    paraPStyle() {
      const s = Object.assign({}, this.bodyTextStyle);
      if (this.paraGap > 0) s.marginBottom = this.paraGap + 'em';
      return s;
    },
    notesRec() {
      return !!(this.analysis && this.analysis.notes_refs);
    },
    notesHint() {
      const n = (this.analysis && this.analysis.notes_refs) || 0;
      return this.$t('epubBeautify.notesDesc', { n });
    },
    noteMarkItems() {
      return [
        { value: 'orig', label: this.$t('epubBeautify.markOrig') },
        { value: 'sym', label: this.$t('epubBeautify.markSym') },
        { value: 'num', label: this.$t('epubBeautify.markNum') },
        { value: 'svg:dot', label: this.$t('epubBeautify.markSvgDot') },
        { value: 'svg:fold', label: this.$t('epubBeautify.markSvgFold') },
        { value: 'svg:inkdrop', label: this.$t('epubBeautify.markSvgInkdrop') },
        { value: 'svg:spark', label: this.$t('epubBeautify.markSvgSpark') },
        { value: 'svg:sealdot', label: this.$t('epubBeautify.markSvgSealdot') },
      ];
    },
    markGlyph() {
      // 选择器旁的即时预览字符（SVG 模板用近似字形示意）
      const map = { orig: '●', sym: '※', num: '[1]', 'svg:dot': '◉', 'svg:fold': '❏', 'svg:inkdrop': '❍', 'svg:spark': '✦', 'svg:sealdot': '▣' };
      return map[this.noteMark] || '●';
    },
    tocSampleRows() {
      const t = (this.analysis && this.analysis.toc_preview_titles) || [];
      if (!t.length) return null;
      return t.slice(0, 5).map((title, i) => [('0' + (i + 1)).slice(-2), title]);
    },
    tocSampleRowsDisplay() {
      // 真实数据优先，空时回落示例并由模板标“示例”避免误为真实目录
      return this.tocSampleRows || this.tocMockRows;
    },
    tocIsMock() {
      return !this.tocSampleRows;
    },
    splitSample() {
      const s = this.chapterSample.trim();
      // 卷级不拆（与后端 _is_volume_text 同口径）
      if (/^\s*(?:[【[]\s*)?(?:第\s*[\d零〇一二三四五六七八九十百千万兩两]+\s*[卷部篇]|0*\d{1,4}\s*卷|卷\s*[\d零〇一二三四五六七八九十百千万兩两]+|[上中下]\s*卷)/i.test(s)) return null;
      const m = s.match(
        /^\s*(第\s*[0-9零〇一二三四五六七八九十百千万兩两]+\s*[章节回篇卷部集季]|(?:chapter|chap\.?)\s*\d+)[\s、．.:：\-—·]*(.+)$/i);
      return m ? [m[1].replace(/\s+/g, ''), m[2]] : null;
    },
    currentPreset() {
      const p = this.presets.find((x) => x.id === this.preset) || this.presets[0] || {};
      // 自定义配色开启且取色器动过时，实时反映到大预览（所见即所得）
      if (this.paletteOn) {
        const merged = Object.assign({}, p);
        if (this.palTouched.accent && this.palAccent) merged.accent = this.palAccent;
        if (this.palTouched.bg && this.palBg) {
          merged.accent_light = this.palBg;
          merged.quote_bg = this.palBg;
        }
        return merged;
      }
      return p;
    },
    currentPresetName() {
      const p = this.currentPreset || {};
      return this.$i18n.locale === 'en' ? (p.name_en || p.id) : (p.name || p.id);
    },
    tocStyleName() {
      const ts = this.tocStyles.find((x) => x.id === this.tocStyle) || {};
      return this.$i18n.locale === 'en' ? (ts.name_en || ts.id) : (ts.name || ts.id);
    },
    recs() {
      const a = this.analysis || {};
      return {
        leading: (a.leading_space_paras || 0) > 0,
        empty: (a.empty_para_est || 0) > 20,
        meta: !!a.calibre_soup || (a.p_close_mismatch_files || 0) > 0,
      };
    },
    cleanCount() {
      return (this.cleanLeading ? 1 : 0) + (this.cleanEmpty ? 1 : 0) + (this.cleanMeta ? 1 : 0);
    },
    cleanLeadingDesc() {
      const n = this.analysis && this.analysis.leading_space_paras;
      return n > 0 ? this.$t('epubBeautify.cleanLeadingRec', { count: n }) : this.$t('epubBeautify.cleanLeadingDesc');
    },
    cleanEmptyDesc() {
      const n = this.analysis && this.analysis.empty_para_est;
      return n > 20 ? this.$t('epubBeautify.cleanEmptyRec', { count: n }) : this.$t('epubBeautify.cleanEmptyDesc');
    },
    cleanMetaDesc() {
      const risky = this.analysis && (this.analysis.calibre_soup || this.analysis.p_close_mismatch_files > 0);
      return risky ? this.$t('epubBeautify.cleanMetaRec') : this.$t('epubBeautify.cleanMetaDesc');
    },
    dialogueHint() {
      const n = this.analysis && this.analysis.dialogue_paras;
      return n > 0
        ? this.$t('epubBeautify.dialogueFound', { count: n })
        : this.$t('epubBeautify.dialogueDesc');
    },
    depthItems() {
      return [
        { value: 0, label: this.$t('epubBeautify.depthAll') },
        { value: 1, label: this.$t('epubBeautify.depthL1') },
        { value: 2, label: this.$t('epubBeautify.depthL2') },
        { value: 3, label: this.$t('epubBeautify.depthL3') },
      ];
    },
    tuneSummary() {
      const fm = { sys: this.$t('epubBeautify.fontModeSys'), orig: this.$t('epubBeautify.fontModeOrig'), mix: this.$t('epubBeautify.fontModeMix') }[this.fontMode] || '';
      const dl = (this.depthItems.find((i) => i.value === this.tocDepth) || {}).label || '';
      const dt = this.pageTint === 'auto' ? this.$t('epubBeautify.pageTintAuto')
        : this.pageTint === 'on' ? this.$t('epubBeautify.pageTintOn') : this.$t('epubBeautify.pageTintOff');
      let s = fm + '｜' + this.$t('epubBeautify.sumClean') + ' ' + this.cleanCount + '/3｜'
        + this.$t('epubBeautify.sumDepth') + ' ' + dl + '｜' + this.$t('epubBeautify.sumTint') + ' ' + dt;
      if (!this.paraIndent) s += '｜' + this.$t('epubBeautify.tuneIndentOff');
      if (this.paraGap > 0) s += '｜' + this.$t('epubBeautify.tuneGap', { n: this.paraGap.toFixed(2) });
      if (this.tocColumns) s += '｜' + this.$t('epubBeautify.tocColumns');
      if (this.notesOn) s += '｜' + this.$t('epubBeautify.tuneNotes');
      if (this.paletteOn) s += '｜' + this.$t('epubBeautify.paletteTitle');
      return s;
    },
    screenBg() {
      if (this.previewTab === 'orig') return '#FFFFFF';
      return this.pageTint === 'on' ? (this.currentPreset.accent_light || '#FFFFFF') : '#FFFFFF';
    },
    screenStyleObj() {
      const s = { background: this.screenBg };
      if (this.bgOn && this.bgObjectUrl) {
        s.backgroundImage = 'url(' + this.bgObjectUrl + ')';
        s.backgroundSize = 'cover';
        s.backgroundPosition = 'center';
        s.backgroundRepeat = 'no-repeat';
      }
      return s;
    },
    runBtnLabel() {
      const base = this.$t('epubBeautify.runBtn');
      return this.batchIds.length ? `${base}(${this.batchIds.length})` : base;
    },
    bodyFont() {
      if (this.fontMode === 'orig' || (this.fontMode === 'mix' && !this.fontBody)) return ORIG_FONT;
      return SYS_BODY_FONT;
    },
    headFont() {
      if (this.fontMode === 'orig' || (this.fontMode === 'mix' && !this.fontHead)) return ORIG_FONT;
      return SYS_HEAD_FONT;
    },
    kaiFont() {
      if (this.fontMode === 'orig' || (this.fontMode === 'mix' && !this.fontKai)) return ORIG_FONT;
      return SYS_KAI_FONT;
    },
    bodyTextStyle() {
      return {
        fontFamily: this.bodyFont,
        lineHeight: String(this.currentPreset.line_height || 1.85),
      };
    },
    dialogueStyle() {
      const p = this.currentPreset || {};
      return {
        fontFamily: this.kaiFont,
        background: p.quote_bg || '#F7F7F7',
        borderLeftColor: p.accent || '#999999',
        color: p.muted || '#666666',
        borderRadius: p.id === 'children' ? '8px' : '4px',
      };
    },
  },
  watch: {
    paletteOn(on) {
      // 开启取色器时用当前预设默认色初始化
      if (on && this.currentPreset) {
        if (!this.palAccent) this.palAccent = this.currentPreset.accent || '#333333';
        if (!this.palBg) this.palBg = this.currentPreset.accent_light || '#F5F5F5';
      }
    },
    preset() {
      // 换预设：重置取色器跟随新预设默认
      this.palAccent = '';
      this.palBg = '';
      this.palTouched.accent = false;
      this.palTouched.bg = false;
    },
  },
  created() {
    this.$store.commit('navbar', true);
    this.loadBgMeta();
  },
  beforeDestroy() {
    this.stopPolling();
    clearTimeout(this.searchDebounce);
    if (this.bgObjectUrl) URL.revokeObjectURL(this.bgObjectUrl);
  },
  methods: {
    hexA(hex, a) {
      const h = String(hex || '#000000').replace('#', '');
      const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
      const v = parseInt(n, 16) || 0;
      return 'rgba(' + ((v >> 16) & 255) + ',' + ((v >> 8) & 255) + ',' + (v & 255) + ',' + a + ')';
    },
    gradLine(hex) {
      return 'linear-gradient(90deg, transparent, ' + this.hexA(hex, 0.55) + ', transparent)';
    },
    togBatch(id) {
      const i = this.batchIds.indexOf(id);
      if (i >= 0) {
        this.batchIds.splice(i, 1);
      } else {
        this.batchIds.push(id);
      }
    },
    async loadBgMeta() {
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/bg_meta');
        const has = !!(rsp.data && rsp.data.has);
        if (has !== this.bgHas || (has && !this.bgObjectUrl)) {
          this.bgHas = has;
          if (has) {
            await this.loadBgPreview();
          } else if (this.bgObjectUrl) {
            URL.revokeObjectURL(this.bgObjectUrl);
            this.bgObjectUrl = '';
            this.bgOn = false;
          }
        }
      } catch (_e) {
        this.bgHas = false;
      }
    },
    async loadBgPreview() {
      try {
        const resp = await fetch('/api/toolbox/epub_beautify/bg_raw');
        if (!resp.ok) return;
        const blob = await resp.blob();
        if (this.bgObjectUrl) URL.revokeObjectURL(this.bgObjectUrl);
        this.bgObjectUrl = URL.createObjectURL(blob);
      } catch (_e) {
        // 预览加载失败不影响功能
      }
    },
    triggerBgUpload() {
      const el = this.$refs.bgFile;
      if (el) el.click();
    },
    async onBgFile(e) {
      const f = e.target.files && e.target.files[0];
      if (!f) return;
      this.bgLoading = true;
      try {
        const fd = new FormData();
        fd.append('file', f);
        const resp = await fetch('/api/toolbox/epub_beautify/bg_upload', { method: 'POST', body: fd });
        const rsp = await resp.json();
        if (rsp.err === 'ok') {
          await this.loadBgMeta();
          this.bgOn = true;
        } else {
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (err) {
        this.resultMsg = String(err);
        this.resultType = 'error';
      } finally {
        this.bgLoading = false;
        e.target.value = '';
      }
    },
    async pickBuiltin(id) {
      this.bgLoading = true;
      try {
        const fd = new FormData();
        fd.append('builtin_id', id);
        const resp = await fetch('/api/toolbox/epub_beautify/bg_upload', { method: 'POST', body: fd });
        const rsp = await resp.json();
        if (rsp.err === 'ok') {
          await this.loadBgMeta();
          this.bgOn = true;
        }
      } finally {
        this.bgLoading = false;
      }
    },
    async delBg() {
      try {
        await fetch('/api/toolbox/epub_beautify/bg_delete', { method: 'POST' });
      } catch (_e) {
        // 忽略网络抖动
      }
      this.bgHas = false;
      this.bgOn = false;
      if (this.bgObjectUrl) {
        URL.revokeObjectURL(this.bgObjectUrl);
        this.bgObjectUrl = '';
      }
    },
    applyCleanupRecommendations() {
      // 按体检结果自动对齐开关（与徽章一致，双向同步）
      this.cleanLeading = !!this.recs.leading;
      this.cleanEmpty = !!this.recs.empty;
      this.cleanMeta = !!this.recs.meta;
    },
    paletteOverridesPayload() {
      // 仅发送与预设默认不同的颜色；未动过取色器则不传（与原始预设对比，避免与已合并的 currentPreset 恒相等）
      if (!this.paletteOn) return null;
      const orig = (this.presets.find((x) => x.id === this.preset) || this.currentPreset || {});
      const norm = (c) => String(c || '').trim().slice(0, 7).toLowerCase();
      const ov = {};
      if (this.palTouched.accent && this.palAccent) {
        const v = norm(this.palAccent);
        if (v && v !== norm(orig.accent)) ov.accent = v;
      }
      if (this.palTouched.bg && this.palBg) {
        const v = norm(this.palBg);
        if (v && v !== norm(orig.accent_light)) ov.accent_light = v;
      }
      return Object.keys(ov).length ? ov : null;
    },
    miniStyle(p) {
      if (p.id === 'inkstone') {
        return { background: p.accent, color: '#FFFFFF', borderRadius: '2px', padding: '7px 4px', textAlign: 'center', fontWeight: 800, letterSpacing: '0.12em', fontSize: '0.8rem' };
      }
      if (p.id === 'xuanzhi') {
        return { color: p.accent, borderBottom: '2px solid ' + p.accent, padding: '9px 4px 6px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.14em', fontSize: '0.8rem' };
      }
      if (p.id === 'vertclassical') {
        return { background: p.accent_light || '#F6F1E3', color: p.accent, writingMode: 'vertical-rl', textOrientation: 'mixed', height: '62px', margin: '0 auto', padding: '4px 6px', borderLeft: '1px solid ' + (p.border || '#DDD'), borderRight: '1px solid ' + (p.border || '#DDD'), fontWeight: 700, letterSpacing: '0.16em', fontSize: '0.78rem' };
      }
      if (p.id === 'modern') {
        return { color: p.accent, borderLeft: '3px solid ' + p.accent, padding: '4px 4px 4px 10px', fontWeight: 700, fontSize: '0.85rem' };
      }
      return { background: p.accent_light || '#F5F5F5', color: p.accent, borderTop: '3px solid ' + p.accent, borderBottom: '1px solid ' + (p.border || '#DDD'), borderRadius: '3px', padding: '8px 4px', textAlign: 'center', fontWeight: 700, letterSpacing: '0.06em', fontSize: '0.8rem' };
    },
    tocMiniFrame(id) {
      const cp = this.currentPreset || {};
      if (id === 'minimal') {
        return { background: '#FFFFFF', border: '1px dashed ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
      }
      if (id === 'cool') {
        return { background: cp.quote_bg || '#F5F5F5', border: '1px solid ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
      }
      return { background: '#FFFFFF', border: '1px solid ' + (cp.border || '#DDD'), borderRadius: '4px', overflow: 'hidden' };
    },
    async search() {
      clearTimeout(this.searchDebounce);
      this.searchDebounce = setTimeout(() => {
        this.doSearch();
      }, 300);
    },
    async doSearch() {
      const q = (this.query || '').trim();
      if (!q) return;
      this.searching = true;
      this.searched = false;
      this.selected = null;
      this.analysis = null;
      this.analysisError = '';
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
      this.analysis = null;
      this.analysisError = '';
      this.resultMsg = '';
      this.resultDetails = [];
      this.progressMsg = '';
      this.searched = false;
    },
    async selectBook(book) {
      if (this.selected && this.selected.id === book.id) {
        this.selected = null;
        this.analysis = null;
        this.analysisError = '';
        return;
      }
      this.selected = book;
      this.analysis = null;
      this.analysisError = '';
      this.resultMsg = '';
      this.newBookId = null;
      this.resultDetails = [];
      const curSeq = ++this.previewSeq;
      const hasEpub = (book.files || []).some((f) => f.format === 'EPUB');
      if (!hasEpub) {
        this.analysisError = this.$t('epubBeautify.noEpub');
        return;
      }
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/preview', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ book_id: book.id }),
        });
        if (this.previewSeq !== curSeq) return;
        if (rsp.err === 'ok') {
          this.analysis = (rsp.data || {}).analysis || null;
          this.presets = (rsp.data || {}).presets || [];
          if ((rsp.data || {}).toc_styles && (rsp.data || {}).toc_styles.length > 0) {
            const raw = (rsp.data || {}).toc_styles || [];
            this.tocStyles = raw.map((s) => {
              if (Array.isArray(s)) {
                const mapEn = { elegant: 'Elegant', cool: 'Cool', seal: 'Seal', minimal: 'Minimal' };
                return { id: s[0], name: s[1], name_en: mapEn[s[0]] || s[0] };
              }
              return s;
            });
          }
          if (this.presets.length > 0) this.preset = this.presets[0].id;
          this.applyCleanupRecommendations();
        } else {
          this.analysisError = rsp.msg || rsp.err;
        }
      } catch (e) {
        if (this.previewSeq !== curSeq) return;
        this.analysisError = String(e);
      }
    },
    stageText(stage) {
      const map = {
        analyzing: this.$t('epubBeautify.progressAnalyzing'),
        processing: this.$t('epubBeautify.progressProcessing'),
        saving: this.$t('epubBeautify.progressSaving'),
        completed: this.$t('epubBeautify.progressCompleted'),
      };
      return map[stage] || '';
    },
    startPolling() {
      this.stopPolling();
      this.pollTimer = setInterval(this.pollProgress, 2000);
    },
    stopPolling() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    async pollProgress() {
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/progress');
        if (rsp.err === 'task.not_found') {
          this.pollNotFound += 1;
          if (this.pollNotFound > 5) {
            this.stopPolling();
            this.processing = false;
            this.resultMsg = this.$t('epubBeautify.taskNotFound');
            this.resultType = 'error';
          }
          return;
        }
        this.pollNotFound = 0;
        const data = rsp.data || {};
        this.progress = data.progress || 0;
        let msg = this.stageText(data.stage);
        if ((data.book_total || 0) > 1) {
          msg = `(${data.book_index || '?'}/${data.book_total}) ${data.current_title || ''} · ${msg}`;
        }
        this.progressMsg = msg;

        if (rsp.err === 'task.failed') {
          this.stopPolling();
          this.processing = false;
          if (rsp.data && rsp.data.results) {
            const fails = (rsp.data.results || []).filter((r) => !r.ok);
            this.resultDetails = fails;
          }
          this.resultMsg = rsp.msg || this.$t('epubBeautify.runFailed');
          this.resultType = 'error';
          return;
        }
        if (data.status === 'completed') {
          this.stopPolling();
          this.processing = false;
          this.progress = 100;
          const results = data.results || [];
          const fails = results.filter((r) => !r.ok);
          if (fails.length) {
            this.resultDetails = fails;
            this.resultMsg = this.$t('epubBeautify.runPartial', { ok: results.length - fails.length, fail: fails.length });
            this.resultType = fails.length === results.length ? 'error' : 'warning';
          } else {
            this.resultDetails = [];
            this.resultMsg = this.$t('epubBeautify.runCompleted');
            this.resultType = 'success';
          }
          this.newBookId = data.new_book_id || null;
          if (!fails.length) this.batchIds = [];
        }
      } catch (_e) {
        // 网络抖动时忽略，继续轮询
      }
    },
    async startRun() {
      if (this.processing || ((!this.selected || this.analysisError) && !this.batchIds.length)) return;
      this.resultMsg = '';
      this.newBookId = null;
      this.processing = true;
      this.progress = 0;
      this.progressMsg = '';
      // 三态映射：sys 全系统栈 / orig 全保留原书 / mix 分档覆盖
      let useSystemFonts;
      let fontOverrides;
      if (this.fontMode === 'orig') {
        useSystemFonts = false;
        fontOverrides = { body: false, head: false, kai: false, code: false };
      } else if (this.fontMode === 'mix') {
        useSystemFonts = true;
        fontOverrides = { body: this.fontBody, head: this.fontHead, kai: this.fontKai, code: this.fontCode };
      } else {
        useSystemFonts = true;
        fontOverrides = { body: true, head: true, kai: true, code: true };
      }
      try {
        const rsp = await this.$backend('/toolbox/epub_beautify/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            book_ids: this.batchIds.length ? this.batchIds.slice() : null,
            book_id: this.batchIds.length ? null : this.selected.id,
            preset: this.preset,
            toc_style: this.tocStyle,
            use_system_fonts: useSystemFonts,
            font_overrides: fontOverrides,
            toc_depth: this.tocDepth || null,
            cleanup: {
              leading: this.cleanLeading,
              empty: this.cleanEmpty,
              meta: this.cleanMeta,
            },
            dialogue: this.dialogue,
            title_split: this.titleSplit,
            para_indent: this.paraIndent,
            para_gap: this.paraGap > 0 ? this.paraGap : null,
            toc_columns: this.tocColumns,
            notes: this.notesOn,
            note_mark: this.noteMark,
            bg_image: this.bgOn && this.bgHas,
            page_tint: this.pageTint === 'auto' ? null : (this.pageTint === 'on'),
            palette_overrides: this.paletteOverridesPayload(),
            suffix: this.suffix,
          }),
        });
        if (rsp.err === 'ok') {
          this.resultMsg = rsp.msg || this.$t('epubBeautify.runStarted');
          this.resultType = 'success';
          this.startPolling();
        } else {
          this.processing = false;
          this.resultMsg = rsp.msg || rsp.err;
          this.resultType = 'error';
        }
      } catch (e) {
        this.processing = false;
        this.resultMsg = String(e);
        this.resultType = 'error';
      }
    },
  },
};
</script>

<style scoped>
.eb-page {
  padding-bottom: 96px;
}
.min-width-0 {
  min-width: 0;
}
.eb-stepnum {
  width: 21px;
  height: 21px;
  border-radius: 50%;
  background: #1976d2;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
}
.eb-stepnum-alt {
  background: #90a4ae;
}
.eb-book-list {
  max-height: 264px;
  overflow-y: auto;
}
.eb-book-item {
  cursor: pointer;
  border: 1.5px solid transparent;
  border-radius: 10px;
  transition: background 0.15s, border-color 0.15s;
}
.eb-book-item:hover {
  background: #f5f8fc;
}
.eb-book-selected {
  border-color: #1976d2;
  background: #eef5fd;
}
.eb-book-title {
  font-weight: 600;
}
.eb-health-head {
  cursor: pointer;
  font-size: 12.5px;
  font-weight: 600;
  color: #888;
  display: flex;
  align-items: center;
  user-select: none;
}
.eb-health-head .v-icon {
  transition: transform 0.2s;
}
.eb-health-head .eb-arr-open {
  transform: rotate(90deg);
}
.eb-toc-preview {
  line-height: 1.7;
}
.eb-pgrid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(148px, 1fr));
  gap: 10px;
}
.eb-pcard {
  border: 1.5px solid #e0e0e0;
  border-radius: 10px;
  padding: 10px;
  cursor: pointer;
  transition: border-color 0.15s, box-shadow 0.15s, transform 0.15s;
  background: #fff;
}
.eb-pcard:hover {
  border-color: #b0bec5;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(23, 42, 79, 0.08);
}
.eb-pcard-selected {
  border-color: var(--pa, #1976d2);
  box-shadow: inset 0 0 0 1px var(--pa, #1976d2), 0 4px 14px rgba(23, 42, 79, 0.08);
}
.eb-rtlb {
  font-size: 9.5px;
  font-weight: 600;
  border: 1px solid #ccc;
  border-radius: 3px;
  padding: 0 4px;
  color: #888;
  margin-left: 5px;
  font-style: normal;
}
.eb-scene {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-swatch {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 3px;
  margin-right: 3px;
  vertical-align: middle;
}
.eb-swatch-b {
  border: 1px solid rgba(0, 0, 0, 0.12);
}
.eb-mini {
  font-size: 0.8rem;
  line-height: 1.5;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-toc-mini {
  font-size: 0.72rem;
  line-height: 1.6;
}
.eb-toc-mock {
  padding: 4px 6px;
  font-weight: 700;
  letter-spacing: 0.2em;
  font-size: 0.78rem;
  text-align: center;
}
.eb-toc-row {
  padding: 3px 8px;
  color: #444;
  border-bottom: 1px dashed #ddd;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-toc-row span {
  margin-right: 4px;
}
.eb-preset {
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  height: 100%;
}
.eb-preset:hover {
  border-color: #90caf9;
}
.eb-preset-selected {
  border-color: #1976d2 !important;
  background: #e3f2fd !important;
}
/* ─── ③ 微调抽屉 ─── */
.eb-panels {
  border-radius: 8px;
}
.eb-tune-head {
  min-height: 56px;
}
.eb-dsum {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  background: #eef2f8 !important;
  font-weight: 500;
}
.eb-grp {
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}
.eb-grp:first-child {
  padding-top: 2px;
}
.eb-grp:last-child {
  border-bottom: none;
  padding-bottom: 0;
}
.eb-count {
  font-size: 10.5px;
  background: #1976d2;
  color: #fff;
  border-radius: 999px;
  padding: 0 7px;
  font-weight: 600;
}
.eb-recb {
  font-size: 10px;
  color: #2e7d32;
  background: #e8f2e8;
  border-radius: 4px;
  padding: 1px 5px;
  font-weight: 600;
}
.eb-crow {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: 3px 0;
}
.eb-fpill {
  font-size: 12px;
  border: 1.5px solid #ddd;
  border-radius: 999px;
  padding: 3px 12px;
  color: #888;
  cursor: pointer;
  user-select: none;
  margin: 2px 6px 2px 0;
  transition: all 0.15s;
}
.eb-fpill.on {
  border-color: #1976d2;
  color: #1976d2;
  background: #eaf2fd;
  font-weight: 600;
}
/* ─── 右栏实时预览 ─── */
.eb-previewcol {
  position: sticky;
  top: 76px;
}
@media (max-width: 1263px) {
  .eb-previewcol {
    position: static;
  }
}
.eb-ptabs {
  width: 100%;
}
.eb-ptabs ::v-deep .v-btn {
  flex: 1;
}
.eb-phone {
  background: #182234;
  border-radius: 26px;
  padding: 10px;
  box-shadow: 0 14px 40px rgba(13, 30, 66, 0.3);
}
.eb-notch {
  width: 86px;
  height: 5px;
  border-radius: 999px;
  background: #33415a;
  margin: 0 auto 8px;
}
.eb-screen {
  border-radius: 17px;
  height: 600px;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px 20px;
  scrollbar-width: thin;
}
.eb-empty-tip {
  text-align: center;
  color: #999;
  padding: 120px 10px 0;
  font-size: 14px;
}
.eb-screen p {
  margin: 0 0 15px;
  font-size: 15px;
  color: #33302b;
}
.eb-indent {
  text-indent: 2em;
}
/* 分段式预览：无缩进（段距由 .eb-screen p 的下边距天然提供） */
.eb-spacing {
  text-indent: 0;
}
.eb-t-card {
  border-top: 3px solid;
  border-bottom: 1px solid;
  text-align: center;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 16px 6px;
  font-size: 17px;
  margin-bottom: 4px;
}
.eb-round {
  border-radius: 10px;
}
.eb-t-ink {
  color: #fff;
  text-align: center;
  font-weight: 800;
  letter-spacing: 0.12em;
  padding: 18px 8px;
  border-radius: 2px;
  font-size: 17px;
  margin-bottom: 4px;
}
.eb-t-xz-wrap {
  padding-top: 56px;
  text-align: center;
  margin-bottom: 4px;
}
.eb-t-xz-title {
  font-weight: 700;
  letter-spacing: 0.18em;
  font-size: 22px;
}
.eb-t-xz-bar {
  display: block;
  width: 34px;
  height: 3px;
  margin-top: 14px;
  border-radius: 2px;
}
.eb-t-leftbar {
  font-weight: 700;
  font-size: 17px;
  border-left: 3px solid;
  padding: 2px 0 2px 12px;
  margin-bottom: 4px;
}
.eb-sep {
  height: 1px;
  width: 74%;
  margin: 12px auto 20px;
}
.eb-sep-dbl {
  height: 4px;
  width: 64%;
  margin: 12px auto 20px;
  border-top: 1px solid;
  border-bottom: 1px solid;
}
.eb-quote {
  padding: 10px 14px;
  margin: 0 0 15px;
  border-left: 3px solid;
  font-size: 14px;
  line-height: 1.9;
}
.eb-dialog-demo {
  border-left: 3px solid !important;
  padding: 0.55em 0.9em !important;
  text-indent: 0 !important;
}
.eb-rt {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.eb-t-num {
  display: block;
  font-size: 0.55em;
  font-weight: 400;
  opacity: 0.8;
  letter-spacing: 0.35em;
  margin-bottom: 0.3em;
}
.eb-t-title {
  display: block;
}
.eb-schip-batch {
  background: #e8f2fd !important;
}
.eb-tex {
  width: 30px;
  height: 42px;
  border-radius: 5px;
  border: 1.5px solid #ddd;
  cursor: pointer;
  margin-right: 7px;
  transition: transform 0.12s, border-color 0.12s;
}
.eb-tex:hover {
  transform: translateY(-1px);
  border-color: #1976d2;
}
.eb-tex-xuanzhi {
  background: linear-gradient(135deg, #f9f4e8, #efe6d2);
}
.eb-tex-parchment {
  background: linear-gradient(135deg, #f2e6c6, #e2d0a6);
}
.eb-tex-linen {
  background: repeating-linear-gradient(45deg, #efebde 0 3px, #e4decd 3px 5px);
}
.eb-bgpick {
  width: 44px;
  height: 62px;
  object-fit: cover;
  border-radius: 5px;
  border: 1px solid var(--v-primary-base, #1976d2);
  margin-left: 10px;
}
.eb-vpad {
  padding-top: 8px;
}
.eb-vbody {
  -webkit-writing-mode: vertical-rl;
  writing-mode: vertical-rl;
  height: 470px;
  margin: 0 auto;
  padding: 16px 14px;
  border-left: 1px solid;
  border-right: 1px solid;
  line-height: 2.1;
  color: #3a3630;
  font-size: 14.5px;
  letter-spacing: 0.08em;
}
.eb-vbody > div {
  margin-left: 12px;
}
.eb-vtitle {
  font-weight: 700;
  font-size: 17px;
  letter-spacing: 0.2em;
}
.eb-vnote {
  text-align: center;
  color: #b9b2a4;
  font-size: 11px;
  margin-top: 10px;
}
.eb-screen-end {
  text-align: center;
  font-size: 11px;
  padding: 14px 0 4px;
  color: #c8c2b6 !important;
}
/* 目录大预览 */
.eb-tocbig {
  font-size: 14px;
  color: #33302b;
}
.eb-toc-cols .eb-toc-frame,
.eb-toc-cols .eb-cool-items,
.eb-toc-cols .eb-min-frame {
  columns: 2;
  column-gap: 1.6em;
}
.eb-toc-cols .eb-tr,
.eb-toc-cols .eb-cool-row,
.eb-toc-cols .eb-min-row,
.eb-toc-cols .eb-seal-row {
  break-inside: avoid;
  -webkit-column-break-inside: avoid;
}
.eb-toc-frame {
  border: 1px solid;
  border-radius: 10px;
  overflow: hidden;
}
.eb-th-elegant {
  border-top: 2px solid;
  text-align: center;
  letter-spacing: 0.32em;
  font-weight: 700;
  padding: 12px;
  font-size: 15px;
}
.eb-th-sub {
  letter-spacing: 0.14em;
  font-size: 9.5px;
  margin-top: 3px;
  font-weight: 400;
}
.eb-tr {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 7.5px 13px;
  border-bottom: 1px dashed;
}
.eb-num-badge {
  font-weight: 700;
  font-size: 11.5px;
  border-radius: 3px;
  padding: 0 5px;
}
.eb-cool-head {
  color: #f5e6d0;
  text-align: center;
  letter-spacing: 0.35em;
  font-weight: 700;
  padding: 14px;
  font-size: 15px;
  border-bottom: 1px solid #c9a96a;
}
.eb-cool-items {
  border-left: 3px solid;
}
.eb-cool-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  border-bottom: 1px solid;
}
.eb-seal-frame {
  padding: 18px 20px;
}
.eb-seal-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid;
  padding-bottom: 9px;
  margin-bottom: 4px;
}
.eb-seal-title {
  letter-spacing: 0.28em;
  font-weight: 700;
  font-size: 15px;
}
.eb-seal-stamp {
  background: #b54942;
  color: #f5e6d0;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 2px;
}
.eb-seal-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 8px 2px;
}
.eb-min-frame {
  padding: 14px 18px;
}
.eb-min-head {
  letter-spacing: 0.32em;
  font-size: 13px;
  font-weight: 600;
  text-align: center;
  padding: 8px 0 12px;
}
.eb-min-row {
  display: flex;
  gap: 12px;
  padding: 7px 2px;
  color: #555;
}
.eb-min-end {
  border-top: 1px solid;
  width: 58%;
  margin: 16px auto 4px;
}
/* ─── 底部操作栏 ─── */
.eb-actionbar {
  position: sticky;
  bottom: 0;
  z-index: 10;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(10px);
  border-top: 1px solid #e8e8e8;
  box-shadow: 0 -6px 24px rgba(23, 42, 79, 0.08);
  margin-top: 24px;
  /* 限制在工具箱容器内：不再 fixed 全视口 */
  width: 100%;
  max-width: 100%;
  border-radius: 12px;
  overflow: hidden;
}
.eb-bar-in {
  max-width: 1240px;
  margin: 0 auto;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.eb-schip {
  background: #eef3fb !important;
  color: #444 !important;
}
.eb-schip-mut {
  color: #999 !important;
}
.eb-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  display: inline-block;
}
</style>
