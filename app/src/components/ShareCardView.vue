<template>
    <div class="text-center share-card-view">
        <div v-if="generating" class="d-flex flex-column align-center">
            <v-progress-circular indeterminate color="primary" size="48"></v-progress-circular>
            <p class="mt-4 grey--text">{{ $t('book.shareCardGenerating') }}</p>
        </div>
        <div v-else-if="imageUrl" class="share-card-frame">
            <img :src="imageUrl" :alt="alt" />
        </div>
    </div>
</template>

<script>
export default {
    name: 'ShareCardView',
    props: {
        imageUrl: { type: String, default: null },
        generating: { type: Boolean, default: false },
        alt: { type: String, default: '' },
    },
};
</script>

<style scoped>
.share-card-view {
    min-height: 200px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-direction: column;
}
.share-card-frame {
    background: #0f0f12;
    border-radius: 24px;
    display: inline-block;
    line-height: 0;
}
.share-card-frame img {
    max-width: 100%;
    display: block;
}
</style>
