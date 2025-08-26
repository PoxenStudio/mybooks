<template>
    <v-row>
        <v-col cols=12 class='text-center position-relative'>
            <div class="watermark">PoxenStudio/Talebook</div>

            <v-divider class='mt-10 mb-3'></v-divider>
            <p class='mb-0 text-center footer-text' v-html="footer_text"></p>
            <p>
                <v-btn small text target="_blank" href="https://github.com/HorkyChen/talebook">Project</v-btn>
                | <v-btn small text target="_blank" href="https://hub.docker.com/r/poxenstudio/talebook">Docker</v-btn>
                | <v-btn small text target="_blank" href="http://talebook.org">DEMO</v-btn>
            </p>
        </v-col>
    </v-row>
</template>

<script>
export default {
    name: 'AppFooter',
    computed: {
        footer_text: function () {
            if (this.$store.state.sys.footer != undefined) {
                return this.$store.state.sys.footer;
            }
            return this.footer;
        },
    },
    footer: function () {
        return this.$t('footer.base_message');
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
    font-size: 4rem;
    font-weight: bold;
    color: rgba(135, 206, 235, 0.3); /* 天蓝色，半透明 */
    pointer-events: none; /* 不影响点击事件 */
    z-index: 0;
    white-space: nowrap;
    user-select: none; /* 不可选中 */
}

</style>
