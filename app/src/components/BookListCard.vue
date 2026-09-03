<template>
    <v-card
        class="booklist-card"
        :style="{ borderLeftColor: borderColor }"
        :to="clickable ? `/booklist/${booklist.id}` : undefined"
    >
        <v-chip v-if="showRecommendBadge && booklist.is_sticky" x-small color="orange" text-color="white" class="booklist-recommend-badge">
            {{ $t('booklist.recommendedBadge') }}
        </v-chip>

        <v-card-text class="pb-2">
            <div class="d-flex align-start">
                <div class="flex-grow-1" style="min-width: 0">
                    <div class="d-flex align-center flex-wrap">
                        <span class="booklist-name text-truncate">{{ booklist.name }}</span>
                        <v-icon v-if="!booklist.is_public" small class="ml-1" color="grey">mdi-lock-outline</v-icon>
                    </div>
                    <div class="booklist-description text-truncate">{{ booklist.description || $t('booklist.noDescription') }}</div>
                </div>

                <div class="booklist-owner d-flex align-center ml-2" @click.stop.prevent>
                    <v-avatar size="28" class="mr-1">
                        <v-img v-if="booklist.owner && booklist.owner.avatar" :src="booklist.owner.avatar"></v-img>
                        <v-icon v-else>mdi-account-circle</v-icon>
                    </v-avatar>
                    <span class="grey--text text-caption text-truncate" style="max-width: 90px">{{ booklist.owner && booklist.owner.username }}</span>
                </div>
            </div>

            <div class="d-flex align-center mt-2 booklist-stats">
                <span class="mr-4"><v-icon x-small class="mr-1">mdi-bookmark-outline</v-icon>{{ booklist.book_count }}</span>
                <span class="mr-4"><v-icon x-small class="mr-1">mdi-eye-outline</v-icon>{{ booklist.view_count }}</span>
                <span class="mr-4 booklist-like" :class="{ 'booklist-like--active': booklist.liked_by_me }" @click.stop.prevent="$emit('toggle-like', booklist)">
                    <v-icon x-small class="mr-1" :color="booklist.liked_by_me ? 'red' : undefined">{{ booklist.liked_by_me ? 'mdi-heart' : 'mdi-heart-outline' }}</v-icon>{{ booklist.like_count }}
                </span>

                <v-spacer></v-spacer>

                <v-btn v-if="isAdmin" x-small text :color="booklist.is_sticky ? 'orange' : undefined" @click.stop.prevent="$emit('toggle-sticky', booklist)">
                    <v-icon x-small left>mdi-pin</v-icon>{{ booklist.is_sticky ? $t('booklist.unpin') : $t('booklist.pin') }}
                </v-btn>

                <v-menu v-if="showManage" offset-y @click.stop.prevent>
                    <template v-slot:activator="{ on, attrs }">
                        <v-btn icon x-small v-bind="attrs" v-on="on" @click.stop.prevent>
                            <v-icon small>mdi-dots-vertical</v-icon>
                        </v-btn>
                    </template>
                    <v-list dense>
                        <v-list-item @click="$emit('edit', booklist)">
                            <v-list-item-icon><v-icon small>mdi-pencil</v-icon></v-list-item-icon>
                            <v-list-item-title>{{ $t('common.edit') }}</v-list-item-title>
                        </v-list-item>
                        <v-list-item @click="$emit('toggle-visibility', booklist)">
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
                                    :style="{ backgroundColor: dark ? c.dark : c.light }"
                                    @click="$emit('change-color', { booklist, color: c.key })"
                                >
                                    <v-icon v-if="booklist.color === c.key" small color="white">mdi-check</v-icon>
                                </v-btn>
                            </v-list>
                        </v-menu>
                        <v-divider></v-divider>
                        <v-list-item @click="$emit('delete', booklist)">
                            <v-list-item-icon><v-icon small color="red">mdi-delete-outline</v-icon></v-list-item-icon>
                            <v-list-item-title class="red--text">{{ $t('common.delete') }}</v-list-item-title>
                        </v-list-item>
                    </v-list>
                </v-menu>
            </div>
        </v-card-text>

        <v-divider></v-divider>

        <div class="booklist-covers">
            <template v-if="covers.length">
                <v-img
                    v-for="c in covers"
                    :key="c.book_id"
                    :src="c.thumb || c.img"
                    class="booklist-cover-item"
                    :aspect-ratio="11 / 15"
                ></v-img>
            </template>
            <div v-else class="booklist-covers-empty grey--text text-caption">{{ $t('booklist.noBooks') }}</div>
        </div>
    </v-card>
</template>

<script>
import { BOOKLIST_COLORS } from '~/utils/booklistColors';

export default {
    name: 'BookListCard',
    props: {
        booklist: { type: Object, required: true },
        isAdmin: { type: Boolean, default: false },
        showManage: { type: Boolean, default: false },
        showRecommendBadge: { type: Boolean, default: false },
        clickable: { type: Boolean, default: true },
    },
    data() {
        return { colors: BOOKLIST_COLORS };
    },
    computed: {
        dark() {
            return this.$vuetify.theme.dark;
        },
        borderColor() {
            const c = this.colors.find(item => item.key === this.booklist.color) || this.colors[0];
            return this.dark ? c.dark : c.light;
        },
        covers() {
            return (this.booklist.cover_books || []).slice(0, 15);
        },
    },
};
</script>

<style scoped>
.booklist-card {
    position: relative;
    border-left-width: 4px;
    border-left-style: solid;
    margin-right: 2px;
}
.booklist-recommend-badge {
    position: absolute;
    top: 8px;
    left: 8px;
    z-index: 1;
}
.booklist-name {
    font-size: 20px;
    font-weight: 700;
    max-width: 100%;
}
.booklist-description {
    font-size: 13px;
    color: var(--v-secondary-base, #757575);
    margin-top: 2px;
}
.text-truncate-2 {
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
}
.booklist-stats {
    font-size: 13px;
}
.booklist-like {
    cursor: pointer;
}
.booklist-like--active {
    color: red;
}
.booklist-color-menu {
    max-width: 160px;
}
.booklist-covers {
    display: flex;
    gap: 4px;
    padding: 8px;
    overflow-x: auto;
}
.booklist-cover-item {
    flex: 0 0 auto;
    width: 60px;
    border-radius: 4px;
}
.booklist-covers-empty {
    padding: 12px;
    width: 100%;
    text-align: center;
}
</style>
