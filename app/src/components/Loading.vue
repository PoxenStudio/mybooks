<template>
    <div v-show="$store.state.loading" class="loading-page">
        <v-progress-circular indeterminate size="40" width="3" color="primary"></v-progress-circular>
    </div>
</template>

<script>
export default {
    data: () => ({
    }),
};
</script>

<style scoped>
/*
 * 首帧遮罩。
 * 原来是一层不透明的纯白全屏底（background: white）+ 128px 的橙色转圈：深色主题下每次
 * 冷启动都先闪一片白，而且因为是不透明且 z-index:1，SSR 已经把内容吐出来了却看不见，
 * 慢网络下等于空白屏。
 *
 * 现在改成半透明 scrim：内容提前可见，只是被压暗；颜色跟随主题，深色下不再有白闪。
 * 尺寸收到 40px、用主色而非橙色 —— 首帧不该比页面本身的品牌色更抢眼。
 */
.loading-page {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(255, 255, 255, 0.72);
    backdrop-filter: blur(2px);
}

.theme--dark .loading-page {
    background: rgba(18, 18, 18, 0.72);
}
</style>
