<template>
    <v-row class="mt-6">
        <v-col cols="12">
            <v-card>
                <v-card-title class="subtitle-1 d-flex align-center flex-wrap">
                    <v-icon left>mdi-comment-text-multiple-outline</v-icon>
                    {{ $t('book.reviewsTitle') }}
                    <v-spacer></v-spacer>
                    <v-tooltip bottom v-if="!loading && !hasOwnReview && canSubmit">
                        <template v-slot:activator="{ on, attrs }">
                            <v-btn icon color="primary" class="ml-2" :aria-label="$t('book.reviewAddHint')" v-bind="attrs" v-on="on" @click="$emit('add')">
                                <v-icon>mdi-plus-circle-outline</v-icon>
                            </v-btn>
                        </template>
                        <span>{{ $t('book.reviewAddHint') }}</span>
                    </v-tooltip>
                </v-card-title>
                <v-card-text>
                    <v-progress-circular
                        v-if="loading"
                        indeterminate
                        color="primary"
                        class="d-block mx-auto my-4"
                    ></v-progress-circular>
                    <template v-else>
                        <p v-if="reviews.length === 0" class="grey--text text-center my-4">
                            {{ $t('book.noReviews') }}
                        </p>
                        <div v-else>
                            <div
                                v-for="r in reviews"
                                :key="r.id"
                                class="review-row d-flex py-3"
                            >
                                <v-avatar size="40" class="mr-3">
                                    <v-img v-if="r.avatar" :src="r.avatar"></v-img>
                                    <v-icon v-else large>mdi-account-circle</v-icon>
                                </v-avatar>
                                <div class="flex-grow-1" style="min-width: 0">
                                    <div class="d-flex align-center flex-wrap">
                                        <span class="font-weight-bold">{{ r.nickname || r.reader_id }}</span>
                                        <v-chip
                                            v-if="r.status === 'pending'"
                                            x-small
                                            color="orange darken-4"
                                            text-color="white"
                                            class="ml-2"
                                        >{{ $t('book.reviewPending') }}</v-chip>
                                        <v-spacer></v-spacer>
                                        <v-icon v-if="r.is_own && canSubmit" small class="ml-1" @click="$emit('edit')">mdi-pencil</v-icon>
                                        <v-icon v-if="isAdmin" small class="ml-1" color="red" @click="remove(r)">
                                            mdi-delete-outline
                                        </v-icon>
                                    </div>
                                    <v-rating
                                        :value="toStars(r.rating)"
                                        color="yellow accent-4"
                                        length="5"
                                        readonly
                                        dense
                                        small
                                    ></v-rating>
                                    <p v-if="r.comment" class="mb-0 mt-1 text-left" style="white-space: pre-wrap; word-break: break-word">{{ r.comment }}</p>
                                </div>
                            </div>
                        </div>
                    </template>
                </v-card-text>
            </v-card>
        </v-col>
    </v-row>
</template>

<script>
import { toStars } from "~/utils/rating";

export default {
    props: {
        bookId: {
            type: [Number, String],
            required: true,
        },
        isAdmin: {
            type: Boolean,
            default: false,
        },
        hasOwnReview: {
            type: Boolean,
            default: false,
        },
        canSubmit: {
            type: Boolean,
            default: true,
        },
    },
    data() {
        return {
            reviews: [],
            total: 0,
            loading: false,
        };
    },
    watch: {
        bookId: {
            immediate: true,
            handler() {
                this.load();
            },
        },
    },
    methods: {
        toStars,
        async load() {
            if (!this.bookId) return;
            this.loading = true;
            try {
                // 不做日期筛选/分页，后端只返回最近更新的最多 50 条
                const rsp = await this.$backend(`/book/${this.bookId}/reviews`);
                if (rsp.err === "ok") {
                    this.reviews = rsp.reviews || [];
                    this.total = rsp.total || 0;
                }
            } catch (e) {
                // 列表加载失败不弹全局报错，避免打断详情页其它内容展示
            } finally {
                this.loading = false;
            }
        },
        async remove(r) {
            try {
                const rsp = await this.$backend("/admin/book-reviews", {
                    method: "POST",
                    body: JSON.stringify({ id: r.id, action: "delete" }),
                });
                if (rsp.err === "ok") {
                    this.$alert("success", rsp.msg || this.$t("book.reviewDeleted"));
                    this.load();
                } else {
                    this.$alert("error", rsp.msg || this.$t("message.operationFailed"));
                }
            } catch (e) {
                this.$alert("error", this.$t("message.networkError"));
            }
        },
        refresh() {
            this.load();
        },
    },
};
</script>

<style scoped>
.review-row + .review-row {
    border-top: 1px solid rgba(128, 128, 128, 0.15);
}
</style>
