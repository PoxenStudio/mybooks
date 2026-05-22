<template>
    <v-card
        class="resource-card"
        :class="{ 'resource-card--dark': $vuetify.theme.dark }"
        @click="openLink"
        style="cursor: pointer;"
    >
        <v-card-text class="d-flex align-center pa-4">
            <!-- Left: Icon -->
            <div class="resource-card__icon-wrap mr-4" @click.stop="openLink">
                <img
                    v-if="icon"
                    :src="icon"
                    :alt="title"
                    class="resource-card__image"
                >
                <v-icon v-else size="40" :color="$vuetify.theme.dark ? '#4a9eca' : 'white'">
                    {{ 'mdi-open-in-new' }}
                </v-icon>
            </div>

            <!-- Right: Title + Description -->
            <div class="resource-card__content d-flex flex-column justify-center flex-grow-1 overflow-hidden"
                :class="{ 'justify-center': !description }"
                @click.stop="openLink"
            >
                <div class="resource-card__title text-subtitle-1 font-weight-bold text-truncate">
                    {{ title }}
                </div>
                <div
                    v-if="description"
                    class="resource-card__description text-body-2 mt-1"
                    :class="$vuetify.theme.dark ? 'grey--text text--lighten-1' : 'grey--text text--darken-1'"
                >
                    {{ description }}
                </div>
            </div>
            <v-icon class="ml-2 resource-card__arrow" :color="$vuetify.theme.dark ? 'grey lighten-1' : 'grey darken-1'" size="20">
                mdi-chevron-right
            </v-icon>
        </v-card-text>
    </v-card>
</template>

<script>
export default {
    name: 'ResourceCard',
    props: {
        icon: {
            type: String,
            default: ''
        },
        title: {
            type: String,
            required: true
        },
        description: {
            type: String,
            default: ''
        },
        link: {
            type: String,
            required: true
        }
    },
    methods: {
        openLink() {
            if (this.link) {
                window.open(this.link, '_blank', 'noopener,noreferrer');
            }
        }
    }
};
</script>

<style scoped>
.resource-card {
    border-radius: 12px !important;
    border: 1px solid rgba(0, 0, 0, 0.1) !important;
    box-shadow:
        0 2px 4px rgba(0, 0, 0, 0.06),
        0 4px 12px rgba(0, 0, 0, 0.08) !important;
    transition: transform 0.2s ease, box-shadow 0.2s ease !important;
}

.resource-card:hover {
    transform: translateY(-3px);
    box-shadow:
        0 6px 16px rgba(0, 0, 0, 0.12),
        0 12px 24px rgba(0, 0, 0, 0.1) !important;
}

.resource-card:active {
    transform: translateY(-1px);
    box-shadow:
        0 3px 8px rgba(0, 0, 0, 0.1),
        0 6px 12px rgba(0, 0, 0, 0.08) !important;
}

.resource-card--dark {
    border-color: rgba(255, 255, 255, 0.1) !important;
    box-shadow:
        0 2px 4px rgba(0, 0, 0, 0.2),
        0 4px 12px rgba(0, 0, 0, 0.3) !important;
}

.resource-card--dark:hover {
    box-shadow:
        0 6px 16px rgba(0, 0, 0, 0.4),
        0 12px 24px rgba(0, 0, 0, 0.3) !important;
}

.resource-card__icon-wrap {
    flex-shrink: 0;
    width: 56px;
    height: 56px;
    border-radius: 14px;
    background: linear-gradient(145deg, rgba(0, 49, 83, 0.12), rgba(0, 49, 83, 0.05));
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: inset 0 1px 3px rgba(0, 0, 0, 0.06), 0 1px 2px rgba(255, 255, 255, 0.08);
}

.theme--dark .resource-card__icon-wrap {
    background: linear-gradient(145deg, rgba(74, 158, 202, 0.18), rgba(74, 158, 202, 0.07));
}

.resource-card__image {
    width: 40px;
    height: 40px;
    object-fit: contain;
    display: block;
}

.resource-card__content {
    min-width: 0;
}

.resource-card__title {
    line-height: 1.3;
}

.resource-card__description {
    display: -webkit-box;
    line-clamp: 2;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    line-height: 1.5;
}

.resource-card__arrow {
    flex-shrink: 0;
    opacity: 0.5;
    transition: opacity 0.2s ease, transform 0.2s ease;
}

.resource-card:hover .resource-card__arrow {
    opacity: 1;
    transform: translateX(2px);
}
</style>
