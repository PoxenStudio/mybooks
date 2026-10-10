<template>
    <div>
        <v-progress-circular v-if="loading && !booklist" indeterminate color="primary" class="d-block mx-auto my-6"></v-progress-circular>

        <template v-else-if="booklist">
            <v-card class="booklist-header-card mb-4" :style="{ borderLeftColor: borderColor }">
                <v-card-text>
                    <div class="d-flex align-start flex-wrap">
                        <div class="flex-grow-1" style="min-width: 0">
                            <div class="d-flex align-center flex-wrap">
                                <span class="booklist-header-name">{{ booklist.name }}</span>
                                <v-icon v-if="!booklist.is_public" small class="ml-2" color="grey">mdi-lock-outline</v-icon>
                                <v-chip v-if="booklist.guest_read && !$store.state.sys.allow.read" x-small color="teal" text-color="white" class="ml-2">
                                    <v-icon x-small left>mdi-lock-open-variant-outline</v-icon>{{ $t('booklist.guestReadBadge') }}
                                </v-chip>
                            </div>
                            <p class="mt-2 mb-2">{{ booklist.description }}</p>
                            <div class="d-flex align-center flex-wrap" style="gap: 16px">
                                <div class="d-flex align-center">
                                    <v-avatar size="28" class="mr-1">
                                        <v-img v-if="booklist.owner && booklist.owner.avatar" :src="booklist.owner.avatar"></v-img>
                                        <v-icon v-else>mdi-account-circle</v-icon>
                                    </v-avatar>
                                    <span class="grey--text text-caption">{{ booklist.owner && booklist.owner.username }}</span>
                                </div>
                                <span><v-icon x-small class="mr-1">mdi-bookmark-outline</v-icon>{{ booklist.book_count }}</span>
                                <span><v-icon x-small class="mr-1">mdi-eye-outline</v-icon>{{ booklist.view_count }}</span>
                                <span class="booklist-like" @click="toggleLike">
                                    <v-icon x-small class="mr-1" :color="booklist.liked_by_me ? 'red' : undefined">{{ booklist.liked_by_me ? 'mdi-heart' : 'mdi-heart-outline' }}</v-icon>{{ booklist.like_count }}
                                </span>
                            </div>
                        </div>
                    </div>
                </v-card-text>

                <div v-if="booklist.is_owner" class="booklist-header-actions d-flex align-center">
                    <v-menu offset-y>
                        <template v-slot:activator="{ on, attrs }">
                            <v-btn icon small v-bind="attrs" v-on="on">
                                <v-icon small>mdi-dots-vertical</v-icon>
                            </v-btn>
                        </template>
                        <v-list dense>
                            <v-list-item @click="openEdit">
                                <v-list-item-icon><v-icon small>mdi-pencil</v-icon></v-list-item-icon>
                                <v-list-item-title>{{ $t('common.edit') }}</v-list-item-title>
                            </v-list-item>
                            <v-list-item @click="toggleVisibility">
                                <v-list-item-icon><v-icon small>{{ booklist.is_public ? 'mdi-lock-outline' : 'mdi-earth' }}</v-icon></v-list-item-icon>
                                <v-list-item-title>{{ booklist.is_public ? $t('booklist.makePrivate') : $t('booklist.makePublic') }}</v-list-item-title>
                            </v-list-item>
                            <v-menu offset-x open-on-hover>
                                <template v-slot:activator="{ on, attrs }">
                                    <v-list-item v-bind="attrs" v-on="on">
                                        <v-list-item-icon><v-icon small>mdi-palette-outline</v-icon></v-list-item-icon>
                                        <v-list-item-title>{{ $t('booklist.changeColor') }}</v-list-item-title>
                                    </v-list-item>
                                </template>
                                <v-list dense class="d-flex flex-wrap booklist-color-menu">
                                    <v-btn
                                        v-for="c in colors"
                                        :key="c.key"
                                        icon
                                        small
                                        class="ma-1"
                                        :style="{ backgroundColor: $vuetify.theme.dark ? c.dark : c.light }"
                                        @click="changeColor(c.key)"
                                    >
                                        <v-icon v-if="booklist.color === c.key" small color="white">mdi-check</v-icon>
                                    </v-btn>
                                </v-list>
                            </v-menu>
                            <v-divider></v-divider>
                            <v-list-item @click="confirmDelete">
                                <v-list-item-icon><v-icon small color="red">mdi-delete-outline</v-icon></v-list-item-icon>
                                <v-list-item-title class="red--text">{{ $t('common.delete') }}</v-list-item-title>
                            </v-list-item>
                        </v-list>
                    </v-menu>
                    <v-btn icon small :disabled="!booklist.is_public" @click="generateShareCard">
                        <v-icon small>mdi-share-variant</v-icon>
                    </v-btn>
                </div>
            </v-card>

            <BookListEditDialog v-model="editDialog" mode="edit" :booklist="booklist" @saved="onSaved" />

            <!-- 书单分享卡片对话框 -->
            <AppDialog
                v-model="dialog_share_card"
                :persistent="false"
                type="action"
                :title="$t('booklist.generateShareCard')"
                icon="mdi-card-bulleted-outline"
                max-width="640"
                :dismiss-label="$t('common.close')"
                :confirm-text="$t('booklist.downloadShareCard')"
                confirm-icon="mdi-download"
                :hide-footer-button="!share_card_image_url || share_card_generating"
                @confirm="downloadShareCard"
            >
                <div class="text-center" style="min-height: 200px; display: flex; align-items: center; justify-content: center; flex-direction: column;">
                    <div v-if="share_card_generating" class="d-flex flex-column align-center">
                        <v-progress-circular indeterminate color="primary" size="48"></v-progress-circular>
                        <p class="mt-4 grey--text">{{ $t('booklist.shareCardGenerating') }}</p>
                    </div>
                    <div v-else-if="share_card_image_url"
                         style="background: #0f0f12; border-radius: 24px; display: inline-block; line-height: 0;">
                        <img :src="share_card_image_url"
                             style="max-width: 100%; display: block;"
                             :alt="booklist.name" />
                    </div>
                </div>
            </AppDialog>

            <AppDialog
                v-model="deleteDialog"
                :persistent="false"
                type="confirm"
                :title="$t('booklist.deleteConfirmTitle')"
                color="deep-orange"
                confirm-dark
                max-width="400"
                :confirm-text="$t('common.delete')"
                :confirm-loading="deleting_loading"
                @confirm="doDelete"
            >
                {{ $t('booklist.deleteConfirmText', { name: booklist.name }) }}
            </AppDialog>

            <div class="d-flex align-center mb-3 flex-wrap" style="gap: 8px">
                <v-select
                    v-model="order"
                    :items="orderOptions"
                    item-text="text"
                    item-value="value"
                    dense
                    outlined
                    hide-details
                    style="max-width: 200px"
                    @change="reload"
                ></v-select>
                <v-spacer></v-spacer>
                <v-btn v-if="booklist.is_owner" color="primary" @click="addDialog = true">
                    <v-icon left>mdi-book-plus-outline</v-icon>
                    {{ $t('booklist.addBooksTitle') }}
                </v-btn>
            </div>

            <v-row v-if="books.length || booklist.is_owner">
                <v-col v-if="booklist.is_owner" cols="4" xs="4" sm="3" md="2" lg="2" xl="1">
                    <v-card class="booklist-add-tile d-flex align-center justify-center" height="100%" @click="addDialog = true">
                        <div class="text-center grey--text">
                            <v-icon large>mdi-plus</v-icon>
                            <div class="text-caption mt-1">{{ $t('booklist.addBooksTitle') }}</div>
                        </div>
                    </v-card>
                </v-col>
                <v-col v-for="b in books" :key="b.book_id" cols="4" xs="4" sm="3" md="2" lg="2" xl="1">
                    <v-tooltip top>
                        <template v-slot:activator="{ on, attrs }">
                            <v-card class="position-relative" v-bind="attrs" v-on="on">
                                <a :href="b.href" target="_blank">
                                    <v-img :src="b.thumb || b.img" :aspect-ratio="11 / 15"></v-img>
                                </a>
                                <div class="text-caption text-truncate pa-1">{{ b.title }}</div>
                                <v-btn
                                    v-if="booklist.is_owner"
                                    icon
                                    class="booklist-remove-btn"
                                    @click="confirmRemove(b)"
                                >
                                    <v-icon color="white">mdi-close-circle</v-icon>
                                </v-btn>
                            </v-card>
                        </template>
                        <span>{{ b.title }}</span>
                    </v-tooltip>
                </v-col>
            </v-row>
            <p v-else class="grey--text text-center my-6">{{ $t('booklist.noBooks') }}</p>

            <div class="text-center mt-4" v-if="hasMore">
                <v-btn text :loading="loading" @click="loadMore">{{ $t('common.loadMore') }}</v-btn>
            </div>

            <BookListAddBooksDialog
                v-model="addDialog"
                :booklist-id="booklist.id"
                :existing-book-ids="books.map(b => b.book_id)"
                @book-added="onBookAdded"
                @book-removed="onBookRemoved"
            />
        </template>

        <p v-else class="grey--text text-center my-6">{{ $t('booklist.notFound') }}</p>

        <!-- Remove Book Confirm Dialog -->
        <AppDialog
            v-model="showRemoveDialog"
            type="confirm"
            :title="$t('booklist.removeConfirmTitle')"
            icon="mdi-close-circle-outline"
            color="deep-orange"
            confirm-dark
            max-width="480px"
            :confirm-text="$t('booklist.removeConfirmTitle')"
            @confirm="doRemoveBook"
        >
            {{ removeTarget ? $t('booklist.removeConfirmText', { title: removeTarget.title }) : '' }}
        </AppDialog>
    </div>
</template>

<script>
import QRCode from 'qrcode';
import BookListAddBooksDialog from '~/components/BookListAddBooksDialog.vue';
import BookListEditDialog from '~/components/BookListEditDialog.vue';
import { BOOKLIST_COLORS } from '~/utils/booklistColors';

export default {
    components: { BookListAddBooksDialog, BookListEditDialog },
    data() {
        return {
            loading: false,
            booklist: null,
            books: [],
            page: 1,
            pageSize: 24,
            booksTotal: 0,
            order: 'desc',
            addDialog: false,
            showRemoveDialog: false,
            removeTarget: null,
            editDialog: false,
            deleteDialog: false,
            deleting_loading: false,
            colors: BOOKLIST_COLORS,
            dialog_share_card: false,
            share_card_generating: false,
            share_card_image_url: null,
        };
    },
    head() {
        return { title: this.booklist ? this.booklist.name : this.$t('booklist.myBooklistsTitle') };
    },
    computed: {
        orderOptions() {
            return [
                { text: this.$t('booklist.orderDesc'), value: 'desc' },
                { text: this.$t('booklist.orderAsc'), value: 'asc' },
            ];
        },
        borderColor() {
            const c = BOOKLIST_COLORS.find(item => item.key === (this.booklist && this.booklist.color)) || BOOKLIST_COLORS[0];
            return this.$vuetify.theme.dark ? c.dark : c.light;
        },
        hasMore() {
            return this.books.length < this.booksTotal;
        },
    },
    mounted() {
        this.fetchDetail();
        this.bumpView();
    },
    methods: {
        async fetchDetail() {
            this.loading = true;
            try {
                const rsp = await this.$backend(`/booklist/${this.$route.params.id}?order=${this.order}&page=${this.page}&page_size=${this.pageSize}`);
                if (rsp.err === 'ok') {
                    this.booklist = rsp.booklist;
                    this.books = this.page === 1 ? rsp.booklist.books : this.books.concat(rsp.booklist.books);
                    this.booksTotal = rsp.booklist.books_total;
                } else {
                    this.booklist = null;
                    this.$alert('error', rsp.msg || this.$t('booklist.notFound'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.loading = false;
            }
        },
        bumpView() {
            this.$backend(`/booklist/${this.$route.params.id}/view`, { method: 'POST' }).catch(() => {});
        },
        reload() {
            this.page = 1;
            this.fetchDetail();
        },
        loadMore() {
            this.page += 1;
            this.fetchDetail();
        },
        async toggleLike() {
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/like`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    this.booklist.liked_by_me = rsp.liked;
                    this.booklist.like_count += rsp.liked ? 1 : -1;
                } else if (rsp.err === 'user.need_login') {
                    this.$router.push('/login');
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        confirmRemove(book) {
            this.removeTarget = book;
            this.showRemoveDialog = true;
        },
        async doRemoveBook() {
            const book = this.removeTarget;
            if (!book) return;
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/books/remove`, {
                    method: 'POST',
                    body: JSON.stringify({ book_id: book.book_id }),
                });
                if (rsp.err === 'ok') {
                    this.books = this.books.filter(b => b.book_id !== book.book_id);
                    this.booklist.book_count = rsp.book_count;
                    this.booksTotal -= 1;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.showRemoveDialog = false;
                this.removeTarget = null;
            }
        },
        onBookAdded() {
            this.page = 1;
            this.fetchDetail();
        },
        onBookRemoved() {
            this.page = 1;
            this.fetchDetail();
        },
        openEdit() {
            this.editDialog = true;
        },
        onSaved() {
            this.fetchDetail();
        },
        async toggleVisibility() {
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/update`, {
                    method: 'POST',
                    body: JSON.stringify({ is_public: !this.booklist.is_public }),
                });
                if (rsp.err === 'ok') {
                    this.booklist.is_public = !this.booklist.is_public;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        async changeColor(color) {
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/update`, {
                    method: 'POST',
                    body: JSON.stringify({ color }),
                });
                if (rsp.err === 'ok') {
                    this.booklist.color = color;
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            }
        },
        confirmDelete() {
            this.deleteDialog = true;
        },
        async doDelete() {
            this.deleting_loading = true;
            try {
                const rsp = await this.$backend(`/booklist/${this.booklist.id}/delete`, { method: 'POST' });
                if (rsp.err === 'ok') {
                    this.$alert('success', rsp.msg || this.$t('message.operationSuccess'));
                    this.deleteDialog = false;
                    this.$router.push('/user/booklists');
                } else {
                    this.$alert('error', rsp.msg || this.$t('message.operationFailed'));
                }
            } catch (e) {
                this.$alert('error', this.$t('message.networkError'));
            } finally {
                this.deleting_loading = false;
            }
        },

        // 生成书单分享卡片
        async generateShareCard() {
            this.share_card_image_url = null;
            this.share_card_generating = true;
            this.dialog_share_card = true;

            try {
                const CARD_W = 480;
                const PADDING = 26;
                const CARD_RADIUS = 0;
                const FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif';
                const ACCENT = '#e2b870';
                const TEXT_COLOR = '#f5f0e8';
                const MUTED_COLOR = '#b0b8c5';
                const COVER_RADIUS = 16;
                const TEXT_W = CARD_W - 2 * PADDING;

                // Section layout heights (kept identical to book share card)
                const HEADER_H = 35;
                const HEADER_GAP = 13;
                const DIVIDER_GAP = 16;
                const TITLE_LINE_H = 45;
                const MAX_TITLE_LINES = 2;
                const TITLE_GAP = 16;
                const MEDIA_H = 320;
                const MEDIA_GAP = 19;
                const DESC_LINE_H = 29;
                const MAX_DESC_LINES = 5;

                // Pre-calculate title line count for dynamic card height
                let titleLineCount = 0;
                {
                    const tmpCanvas = document.createElement('canvas');
                    tmpCanvas.width = CARD_W;
                    tmpCanvas.height = 10;
                    const tmpCtx = tmpCanvas.getContext('2d');
                    tmpCtx.font = `bold 32px ${FONT}`;
                    const chars = Array.from(this.booklist.name || '');
                    let idx = 0;
                    while (idx < chars.length && titleLineCount < MAX_TITLE_LINES) {
                        let line = '';
                        while (idx < chars.length) {
                            const next = line + chars[idx];
                            if (tmpCtx.measureText(next).width > TEXT_W) break;
                            line = next;
                            idx++;
                        }
                        if (!line) { idx++; } else { titleLineCount++; }
                    }
                    if (titleLineCount === 0) titleLineCount = 1;
                }

                // Description pre-measure
                const descText = (this.booklist.description || '').trim();
                const hasDesc = !!descText;
                let descLineCount = 0;
                if (hasDesc) {
                    const tmpCanvas = document.createElement('canvas');
                    tmpCanvas.width = CARD_W;
                    tmpCanvas.height = 10;
                    const tmpCtx = tmpCanvas.getContext('2d');
                    tmpCtx.font = `19px ${FONT}`;
                    const chars = Array.from(descText);
                    let idx = 0;
                    while (idx < chars.length && descLineCount < MAX_DESC_LINES) {
                        let line = '';
                        while (idx < chars.length) {
                            const next = line + chars[idx];
                            if (tmpCtx.measureText(next).width > TEXT_W) break;
                            line = next;
                            idx++;
                        }
                        if (!line) { idx++; } else { descLineCount++; }
                    }
                }

                // Compute total card height based on content
                let CARD_H = PADDING
                    + HEADER_H + HEADER_GAP + 1 + DIVIDER_GAP
                    + titleLineCount * TITLE_LINE_H + TITLE_GAP
                    + MEDIA_H;
                if (descLineCount > 0) {
                    CARD_H += MEDIA_GAP + descLineCount * DESC_LINE_H;
                }
                CARD_H += PADDING;

                // Helper: rounded rect path
                const roundedRectPath = (c, x, y, w, h, r) => {
                    c.beginPath();
                    c.moveTo(x + r, y);
                    c.lineTo(x + w - r, y);
                    c.quadraticCurveTo(x + w, y, x + w, y + r);
                    c.lineTo(x + w, y + h - r);
                    c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
                    c.lineTo(x + r, y + h);
                    c.quadraticCurveTo(x, y + h, x, y + h - r);
                    c.lineTo(x, y + r);
                    c.quadraticCurveTo(x, y, x + r, y);
                    c.closePath();
                };

                // Helper: truncated multi-line text
                const fillTruncatedText = (text, x, y, maxW, lineH, maxLines) => {
                    const chars = Array.from(text);
                    let idx = 0;
                    const lines = [];
                    while (idx < chars.length && lines.length < maxLines) {
                        let line = '';
                        while (idx < chars.length) {
                            const next = line + chars[idx];
                            if (ctx.measureText(next).width > maxW) break;
                            line = next;
                            idx++;
                        }
                        if (!line) { line = chars[idx] || ''; idx++; }
                        lines.push(line);
                    }
                    if (idx < chars.length && lines.length > 0) {
                        const ellipsis = '…';
                        let last = Array.from(lines[lines.length - 1]);
                        while (last.length > 0 && ctx.measureText(last.join('') + ellipsis).width > maxW) last.pop();
                        lines[lines.length - 1] = last.join('') + ellipsis;
                    }
                    lines.forEach((l, i) => ctx.fillText(l, x, y + i * lineH));
                    return lines.length;
                };

                // Helper: shuffle a copy of the array (Fisher-Yates)
                const shuffle = (arr) => {
                    const a = arr.slice();
                    for (let i = a.length - 1; i > 0; i--) {
                        const j = Math.floor(Math.random() * (i + 1));
                        [a[i], a[j]] = [a[j], a[i]];
                    }
                    return a;
                };

                // Create canvas (transparent by default — corners stay transparent after clip)
                const canvas = document.createElement('canvas');
                canvas.width = CARD_W;
                canvas.height = CARD_H;
                const ctx = canvas.getContext('2d');

                ctx.shadowColor = 'transparent';
                ctx.shadowBlur = 0;

                // Background with rounded clip so corners remain transparent in PNG
                ctx.save();
                roundedRectPath(ctx, 0, 0, CARD_W, CARD_H, CARD_RADIUS);
                ctx.clip();

                ctx.fillStyle = '#003153';
                ctx.fillRect(0, 0, CARD_W, CARD_H);

                // Subtle noise texture
                for (let i = 0; i < 80; i++) {
                    const alpha = (0.1 + Math.random() * 0.3).toFixed(2);
                    ctx.fillStyle = `rgba(255,62,47,${alpha})`;
                    const r = 1 + Math.random() * 10;
                    ctx.beginPath();
                    ctx.arc(Math.random() * CARD_W, Math.random() * CARD_H, r, 0, Math.PI * 2);
                    ctx.fill();
                }

                ctx.textAlign = 'left';
                ctx.textBaseline = 'top';
                let curY = PADDING;

                // --- Section 1: Header (siteTitle left + date right) ---
                const siteTitle = localStorage.getItem('sys_title') || 'MyBooks';
                ctx.font = `500 19px ${FONT}`;
                ctx.fillStyle = TEXT_COLOR;
                ctx.fillText(siteTitle, PADDING, curY + Math.round((HEADER_H - 19) / 2));

                const now = new Date();
                const dateStr = `${now.getFullYear()}.${String(now.getMonth() + 1).padStart(2, '0')}.${String(now.getDate()).padStart(2, '0')}`;
                ctx.font = `16px ${FONT}`;
                ctx.fillStyle = MUTED_COLOR;
                const dateW = ctx.measureText(dateStr).width;
                ctx.fillText(dateStr, CARD_W - PADDING - dateW, curY + Math.round((HEADER_H - 16) / 2));

                curY += HEADER_H + HEADER_GAP;

                // Divider line (full width)
                ctx.strokeStyle = ACCENT + '60';
                ctx.lineWidth = 1;
                ctx.beginPath();
                ctx.moveTo(PADDING, curY);
                ctx.lineTo(CARD_W - PADDING, curY);
                ctx.stroke();
                curY += 1 + DIVIDER_GAP;

                // --- Section 2: Booklist name (up to MAX_TITLE_LINES lines, centered) ---
                ctx.font = `bold 32px ${FONT}`;
                ctx.fillStyle = TEXT_COLOR;
                ctx.textAlign = 'center';
                fillTruncatedText(this.booklist.name || '', CARD_W / 2, curY, TEXT_W, TITLE_LINE_H, MAX_TITLE_LINES);
                ctx.textAlign = 'left';
                curY += titleLineCount * TITLE_LINE_H + TITLE_GAP;

                // --- Section 3: Cover collage (left half) + QR (right half), height = MEDIA_H ---
                const mediaY = curY;
                const HALF_W = Math.floor(TEXT_W / 2);

                // Collage box: centered in left half, proportional to book cover ratio (11:15)
                const coverMaxW = HALF_W - 12;
                const coverRenderH = Math.min(MEDIA_H - 8, Math.round(coverMaxW * 15 / 11));
                const coverRenderW = Math.round(coverRenderH * 11 / 15);
                const coverX = Math.round(PADDING + (HALF_W - coverRenderW) / 2);
                const coverY = Math.round(mediaY + (MEDIA_H - coverRenderH) / 2);

                const loadImg = (src) => new Promise((resolve) => {
                    const img = new Image();
                    img.crossOrigin = 'anonymous';
                    img.onload = () => resolve(img);
                    img.onerror = () => resolve(null);
                    img.src = src;
                });

                // First 5 books of the booklist (current sort order), randomly shuffled
                const coverSrcs = this.books.slice(0, 5).map(b => b.thumb || b.img).filter(Boolean);
                const shuffledSrcs = shuffle(coverSrcs);
                const centerSrc = shuffledSrcs[0];
                const gridSrcs = shuffledSrcs.slice(1);
                const [centerImg, ...gridImgs] = await Promise.all([loadImg(centerSrc), ...gridSrcs.map(loadImg)]);
                const loadedGridImgs = gridImgs.filter(Boolean);

                if (!centerImg && loadedGridImgs.length === 0) {
                    ctx.fillStyle = '#2a2a2e';
                    roundedRectPath(ctx, coverX, coverY, coverRenderW, coverRenderH, COVER_RADIUS);
                    ctx.fill();
                    ctx.fillStyle = MUTED_COLOR;
                    ctx.font = `16px ${FONT}`;
                    ctx.textAlign = 'center';
                    ctx.fillText('📖', coverX + coverRenderW / 2, coverY + coverRenderH / 2);
                    ctx.textAlign = 'left';
                } else {
                    // 4 covers tiled 2x2 as background, each with a slight random rotation/offset for a collage feel
                    ctx.save();
                    roundedRectPath(ctx, coverX, coverY, coverRenderW, coverRenderH, COVER_RADIUS);
                    ctx.clip();
                    ctx.fillStyle = '#12222c';
                    ctx.fillRect(coverX, coverY, coverRenderW, coverRenderH);

                    const tileW = coverRenderW / 2;
                    const tileH = coverRenderH / 2;
                    const quadrants = [
                        { x: coverX, y: coverY },
                        { x: coverX + tileW, y: coverY },
                        { x: coverX, y: coverY + tileH },
                        { x: coverX + tileW, y: coverY + tileH },
                    ];
                    quadrants.forEach((q, i) => {
                        if (loadedGridImgs.length === 0) return;
                        const img = loadedGridImgs[i % loadedGridImgs.length];
                        const cx = q.x + tileW / 2;
                        const cy = q.y + tileH / 2;
                        const angle = (Math.random() * 16 - 8) * Math.PI / 180;
                        const jitter = 6;
                        const dx = (Math.random() * 2 - 1) * jitter;
                        const dy = (Math.random() * 2 - 1) * jitter;
                        const overscan = 1.25;
                        const iw = tileW * overscan;
                        const ih = tileH * overscan;
                        ctx.save();
                        ctx.translate(cx + dx, cy + dy);
                        ctx.rotate(angle);
                        ctx.drawImage(img, -iw / 2, -ih / 2, iw, ih);
                        ctx.restore();
                    });
                    ctx.restore();

                    ctx.save();
                    ctx.strokeStyle = ACCENT + '40';
                    ctx.lineWidth = 1.5;
                    roundedRectPath(ctx, coverX, coverY, coverRenderW, coverRenderH, COVER_RADIUS);
                    ctx.stroke();
                    ctx.restore();

                    // 5th cover centered on top, slightly rotated, with shadow + border (same style as the book cover)
                    if (centerImg) {
                        const centerW = coverRenderW * 0.62;
                        const centerH = coverRenderH * 0.62;
                        const ccx = coverX + coverRenderW / 2;
                        const ccy = coverY + coverRenderH / 2;
                        const cAngle = (Math.random() * 20 - 10) * Math.PI / 180;

                        ctx.save();
                        ctx.translate(ccx, ccy);
                        ctx.rotate(cAngle);
                        ctx.shadowColor = 'rgba(0,0,0,0.4)';
                        ctx.shadowBlur = 10;
                        ctx.shadowOffsetX = 2;
                        ctx.shadowOffsetY = 4;
                        roundedRectPath(ctx, -centerW / 2, -centerH / 2, centerW, centerH, COVER_RADIUS);
                        ctx.clip();
                        ctx.drawImage(centerImg, -centerW / 2, -centerH / 2, centerW, centerH);
                        ctx.restore();

                        ctx.save();
                        ctx.translate(ccx, ccy);
                        ctx.rotate(cAngle);
                        ctx.shadowBlur = 0;
                        ctx.strokeStyle = ACCENT + '40';
                        ctx.lineWidth = 1.5;
                        roundedRectPath(ctx, -centerW / 2, -centerH / 2, centerW, centerH, COVER_RADIUS);
                        ctx.stroke();
                        ctx.restore();
                    }
                }

                // QR: centered in right half, points to the booklist detail page
                const QR_SIZE = Math.min(144, HALF_W - 32);
                const QR_LABEL_H = 22;
                const qrHalfW = TEXT_W - HALF_W;
                const qrCenterX = PADDING + HALF_W + Math.round(qrHalfW / 2);
                const qrX = Math.round(qrCenterX - QR_SIZE / 2);
                const qrTotalH = QR_SIZE + 6 + QR_LABEL_H;
                const qrY = Math.round(mediaY + (MEDIA_H - qrTotalH) / 2);

                // Light background panel behind QR for readability
                const qrBgPad = 4;
                ctx.fillStyle = '#f5efe5';
                roundedRectPath(ctx, qrX - qrBgPad, qrY - qrBgPad, QR_SIZE + qrBgPad * 2, QR_SIZE + qrBgPad * 2, 8);
                ctx.fill();

                const viewUrl = `${window.location.origin}/booklist/${this.booklist.id}`;
                const qrCanvas = document.createElement('canvas');
                await QRCode.toCanvas(qrCanvas, viewUrl, {
                    width: QR_SIZE,
                    margin: 1,
                    color: { dark: '#1f1f28', light: '#f5efe5' },
                });
                ctx.drawImage(qrCanvas, qrX, qrY, QR_SIZE, QR_SIZE);

                ctx.font = `16px ${FONT}`;
                ctx.fillStyle = MUTED_COLOR;
                ctx.textAlign = 'center';
                ctx.fillText('扫码查看', qrCenterX, qrY + QR_SIZE + 8);
                ctx.textAlign = 'left';

                curY = mediaY + MEDIA_H;

                // --- Section 4: Description (up to 5 lines) ---
                if (descLineCount > 0) {
                    curY += MEDIA_GAP;
                    ctx.font = `12px ${FONT}`;
                    ctx.globalAlpha = 0.87;
                    ctx.fillStyle = TEXT_COLOR;
                    fillTruncatedText(descText, PADDING, curY, TEXT_W, DESC_LINE_H, MAX_DESC_LINES);
                    ctx.globalAlpha = 1;
                }

                ctx.restore(); // Restore clip (transparent corners preserved)

                // Outer glow border
                ctx.save();
                ctx.shadowBlur = 0;
                ctx.strokeStyle = ACCENT + '30';
                ctx.lineWidth = 2;
                roundedRectPath(ctx, 2, 2, CARD_W - 4, CARD_H - 4, CARD_RADIUS);
                ctx.stroke();
                ctx.restore();

                this.share_card_image_url = canvas.toDataURL('image/png');

            } catch (err) {
                console.error('生成书单分享卡片失败:', err);
                this.$alert('error', this.$t('booklist.shareCardFailed'));
                this.dialog_share_card = false;
            } finally {
                this.share_card_generating = false;
            }
        },

        // 下载书单分享卡片
        downloadShareCard() {
            if (!this.share_card_image_url) return;
            const a = document.createElement('a');
            const safeName = (this.booklist.name || 'booklist').replace(/[/\\:*?"<>|]/g, '_');
            a.download = `${safeName}_分享卡片.png`;
            a.href = this.share_card_image_url;
            a.click();
        },
    },
};
</script>

<style scoped>
.booklist-header-card {
    position: relative;
    border-left-width: 6px;
    border-left-style: solid;
}
.booklist-header-actions {
    position: absolute;
    right: 8px;
    bottom: 8px;
}
.booklist-color-menu {
    max-width: 160px;
}
.booklist-header-name {
    font-size: 28px;
    font-weight: 700;
}
.booklist-like {
    cursor: pointer;
}
.booklist-add-tile {
    cursor: pointer;
    border: 2px dashed rgba(128, 128, 128, 0.4);
    min-height: 140px;
}
.position-relative {
    position: relative;
}
.booklist-remove-btn {
    position: absolute;
    top: 1px;
    right: 1px;
    background: rgba(0, 0, 0, 0.5);
}
</style>
