<template>
    <v-row>
        <v-col cols=12 xs=12 sm=6 md=4 lg=3 xl=2 v-for="(book,idx) in render_books" :key="idx+'-books-'+book.id" class="book-list-card d-flex">
            <v-card :to="book.href" class="flex-grow-1" >
                <v-row>
                    <v-col cols=4 xs=4 sm=4 md=4 lg=4 class='col-book-img'>
                        <div class="book-img-container">
                            <v-img :src="book.thumb || book.img" :aspect-ratio="11/15" style="border-radius: 12px;" class="book-img-hover"></v-img>
                            <!-- 实体书角标 -->
                            <div v-if="book.book_type === 1" class="physical-book-badge">
                                <v-icon small color="white">mdi-bookshelf</v-icon>
                            </div>
                            <!-- 音频书角标 -->
                            <div v-if="isAudioPage || book.has_audio" class="audio-book-badge">
                                <v-icon small color="white">mdi-headphones</v-icon>
                            </div>
                        </div>
                    </v-col>
                    <v-col cols=8 xs=8 sm=8 md=8 lg=8 class='col-book-info'>
                        <v-card-text class="pb-0 d-flex flex-column" align-left>
                            <div class="book-title">{{book.title}}</div>
                            <div class="d-flex flex-wrap align-center">
                                <v-chip rounded x-small color="green" class="white--text ma-1" v-if="book.category">
                                    {{ book.category }}
                                </v-chip>
                                <template v-for="(file, index) in book.files?.slice(0, 2)" :key="'format-' + index">
                                    <v-chip rounded x-small class="ma-1"
                                        color="cyan"
                                        text-color="white"
                                        style="padding: 0px 2px; font-weight: bold; margin: 1px !important;"
                                    >{{ file.format }}</v-chip>
                                </template>
                            </div>
                            <slot name="introduce" :book="book"></slot>
                            <div class="book-comments flex-grow-1">
                                <p v-if="book.comments && shouldShowCommentTooltip(book.comments)"
                                    v-html="book.comments"
                                    class="comment-tooltip-activator"
                                    @mouseenter="showTooltip($event, book.comments)"
                                    @mouseleave="hideTooltip"
                                ></p>
                                <p v-else-if="book.comments" v-html="book.comments"></p>
                                <p v-else>{{ $t('bookCards.browseDetails') }}</p>
                            </div>
                        </v-card-text>
                    </v-col>
                </v-row>
                <slot name="actions" :book="book"></slot>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
export default {
    props: {
        books: Array,
        isAudioPage: {
            type: Boolean,
            default: false
        }
    },
    components: {
    },
    computed: {
        render_books: function() {
            return (this.books || []).map( b => {
                // 确保b是一个对象
                if (!b) return {};

                if ( b['href'] == undefined ) {
                    if (this.isAudioPage) {
                        b['href'] = "/audio/" + (b.id || '');
                    } else {
                        b['href'] = "/book/" + (b.id || '');
                    }
                }
                return b;
            }).filter(Boolean); // 过滤掉空对象
        },
    },
    methods: {
        shouldShowCommentTooltip(html) {
            return this.isLongComment(html) && !this.isSmallScreen();
        },
        isSmallScreen() {
            return Boolean(this.$vuetify?.breakpoint?.smAndDown);
        },
        buildCommentPreview(html) {
            if (!html) return '';
            let text = String(html)
                .replace(/<br\s*\/?\s*>/gi, ' ')
                .replace(/<\/p>/gi, ' ')
                .replace(/<[^>]+>/g, '')
                .replace(/&nbsp;/gi, ' ')
                .replace(/&amp;/gi, '&')
                .replace(/&lt;/gi, '<')
                .replace(/&gt;/gi, '>')
                .replace(/\s+/g, ' ')
                .trim();

            if (text.length > 200) {
                text = text.slice(0, 200) + '...';
            }
            return text;
        },
        isLongComment(html) {
            if (!html) return false;
            let text = String(html).replace(/<[^>]+>/g, '').replace(/&nbsp;/gi, ' ').trim();
            return text.length > 80;
        },
        getOrCreateTooltipEl() {
            let el = document.getElementById('bc-global-tooltip');
            if (!el) {
                el = document.createElement('div');
                el.id = 'bc-global-tooltip';
                el.style.cssText = [
                    'position:fixed',
                    'z-index:9999',
                    'background:#003153',
                    'color:#fff',
                    'border-radius:4px',
                    'padding:6px 10px',
                    'font-size:12px',
                    'line-height:1.5',
                    'max-width:360px',
                    'white-space:normal',
                    'word-break:break-word',
                    'pointer-events:none',
                    'box-shadow:0 2px 12px rgba(0,0,0,0.3)',
                    'display:none',
                ].join(';');
                document.body.appendChild(el);
            }
            return el;
        },
        showTooltip(event, html) {
            const text = this.buildCommentPreview(html);
            const el = this.getOrCreateTooltipEl();
            el.textContent = text;
            el.style.transform = '';
            el.style.display = 'block';
            const rect = event.currentTarget.getBoundingClientRect();
            const gap = 8;
            const vpW = window.innerWidth;
            const ttW = el.offsetWidth;
            let left = rect.left + rect.width / 2 - ttW / 2;
            left = Math.max(8, Math.min(left, vpW - ttW - 8));
            el.style.left = left + 'px';
            const ttH = el.offsetHeight;
            if (rect.top - ttH - gap < 8) {
                el.style.top = (rect.bottom + gap) + 'px';
            } else {
                el.style.top = (rect.top - ttH - gap) + 'px';
            }
        },
        hideTooltip() {
            const el = document.getElementById('bc-global-tooltip');
            if (el) el.style.display = 'none';
        },
    },
    beforeDestroy() {
        this.hideTooltip();
    },
    // vue3 compatible alias
    beforeUnmount() {
        this.hideTooltip();
    },
    // hide on scroll
    mounted() {
        this._scrollHide = () => this.hideTooltip();
        window.addEventListener('scroll', this._scrollHide, true);
    },
    destroyed() {
        window.removeEventListener('scroll', this._scrollHide, true);
    },
    unmounted() {
        window.removeEventListener('scroll', this._scrollHide, true);
    },
    data: () => {
        return {
        }
    },
}
</script>

<style scoped>
.book-title {
    display: block;
    /*height: 1em;*/
    overflow: hidden;
    display: -webkit-box;
    -webkit-line-clamp: 1;
    line-clamp: 1;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    text-align: left;
    font-weight: bold;
}
.book-list-card .v-card {
    min-height: 6em;
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    overflow: hidden;
}
.book-list-card .v-card > .row {
    flex: 1;
    margin: 0;
}
.book-list-card .v-card-text {
    height: 100%;
}
.book-comments {
    display: -webkit-box;
    -webkit-line-clamp: 3;
    line-clamp: 3;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    margin-top: 3px;
    margin-bottom: 3px;
    text-align: left;
    overflow: hidden;
}
.book-comments p {
    font-size: small;
    margin-bottom: 0px;
}

.comment-tooltip-activator {
    cursor: pointer;
}

.book-list-card .row {
    margin-bottom: 0px;
}
.page-title {
    font-weight: bold;
    text-align: left;
}
.col-book-img {
    padding: 6px 0 0 3px;
    display: flex;
    flex-direction: column;
}
.book-img-container {
    position: relative;
    display: flex;
    width: 100%;
    aspect-ratio: 3/4;
}
.book-img-container .v-image {
    width: 100%;
    height: 100%;
}
.physical-book-badge {
    position: absolute;
    top: 6px;
    left: 6px;
    background-color: #2196F3;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(33, 150, 243, 0.4);
    z-index: 3;
}
.audio-book-badge {
    position: absolute;
    top: 6px;
    right: 6px;
    background-color: #9C27B0;
    border-radius: 50%;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 2px 8px rgba(156, 39, 176, 0.4);
    z-index: 3;
}
.col-book-info {
    padding: 0;
    margin-left: -6px;
    margin-top: -6px;
}
.book-img-hover {
    transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}
.book-img-hover:hover {
    overflow-clip-margin: content-box;
    overflow: clip;
    transform: scale(1.06);
    z-index: 2;
    box-shadow: 0 8px 24px rgba(0,0,0,0.18);
}
</style>
