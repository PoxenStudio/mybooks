<template>
    <div>
    <v-row>
        <v-col cols=12 class='text-center position-relative'>
            <div class="watermark" v-if="footer_watermark" v-text="footer_watermark"></div>

            <v-divider class='mt-10 mb-3'></v-divider>
            <p class='mb-0 text-center footer-text' v-html="footer_text" v-if="footer_text"></p>
            <p>
                <v-btn small text target="_blank" v-if="!hide_project_links" href="https://github.com/PoxenStudio/mybooks">Project</v-btn>
                <span v-if="!hide_project_links">|</span>
                <v-btn small text target="_blank" href="/podcast">Podcast</v-btn>
                <span>|</span>
                <v-btn small text target="_blank" v-if="!hide_project_links" href="https://mybooks.top">MyBooks</v-btn>
                <span v-if="!hide_project_links">|</span>
                <v-btn small text target="_blank" href="/opds-readme"> {{ $t('appHeader.opdsIntroduction') }}</v-btn>
                <span>|</span>
                <v-btn small text target="_blank" href="/webdav-readme"> {{ $t('appHeader.webdavIntroduction') }} </v-btn>
                <span>|</span>
                <v-btn small text target="_blank" href="https://github.com/PoxenStudio/MyReader"> MyReader </v-btn>
            </p>
            <p v-if="version" class="version-info cursor-pointer" @click="showReleaseNotes">
                {{ $t('appHeader.systemVersion') }}: {{ version }} {{ standalone ? '(Standalone)' : '' }}
            </p>
        </v-col>
    </v-row>

    <v-dialog v-model="releaseNotesDialog" max-width="480" persistent transition="dialog-bottom-transition">
        <v-card class="release-notes-card">
            <v-card-title class="headline text-center">
                {{ $t('index.versionChanges') }}
            </v-card-title>
            <v-card-text class="release-notes-card">
                <div v-html="releaseNotesContent" style="max-height: 440px; overflow-y: auto;"></div>
            </v-card-text>
            <v-card-actions class="justify-center">
                <v-btn rounded large color="primary" dark elevation="2" @click="closeReleaseNotesDialog">
                    {{ $t('common.close') }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
    </div>
</template>

<script>
export default {
    name: 'AppFooter',
    props: {
        footer: {
            type: String,
            default: '',
        },
    },
    data: function () {
        return {
            releaseNotesDialog: false,
            releaseNotesContent: '',
        };
    },
    computed: {
        footer_text: function () {
            const storeFooter = this.$store && this.$store.state && this.$store.state.sys
                ? this.$store.state.sys.footer
                : undefined;
            const raw = storeFooter !== undefined ? storeFooter : (this.footer || '');
            if (raw == null) return '';
            const trimmed = String(raw).trim();
            return trimmed === '' ? '' : raw;
        },
        standalone: function () {
            return this.$store.state.sys.standalone || false;
        },
        footer_watermark: function () {
            return this.$store.state.sys.footer_watermark || '';
        },
        hide_project_links: function () {
            return this.$store.state.sys.hide_project_links || false;
        },
        version: function () {
            return this.$store.state.sys.version || '';
        },
    },
    methods: {
        async showReleaseNotes() {
            try {
                const rsp = await this.$backend('/admin/release/notes?force=true');
                if (rsp.err === 'ok' && rsp.msg) {
                    this.releaseNotesContent = rsp.msg;
                    this.releaseNotesDialog = true;
                }
            } catch (error) {
                console.error('Failed to load release notes:', error);
            }
        },
        closeReleaseNotesDialog() {
            this.releaseNotesDialog = false;
        },
    },
}
</script>

<style>
.position-relative {
    position: relative;
}

.watermark {
    position: absolute;
    top: 75%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-family: 'Times New Roman', serif;
    font-size: clamp(2rem, 5vw, 3rem);    /* 在 2rem–3rem 之间，按屏幕宽度自适应 */
    font-weight: bold;
    color: rgba(200, 200, 200, 0.2); /* 浅灰色，半透明 */
    pointer-events: none;
    z-index: 0;
    white-space: nowrap;
    user-select: none;
}

.version-info {
    color: #666;
    font-size: 12px;
    margin-top: 8px;
    margin-bottom: 8px;
}

.theme--dark .version-info {
    color: #fff;
}

.cursor-pointer {
    cursor: pointer;
    transition: color 0.2s ease;
}

.cursor-pointer:hover {
    color: #333;
}

.theme--dark .cursor-pointer:hover {
    color: #ccc;
}

/* Release Notes Dialog card font size */
.release-notes-card {
    font-size: 16px;
}

/* Ensure close button text is also 16px */
.release-notes-card .v-btn {
    font-size: 16px !important;
}


</style>
