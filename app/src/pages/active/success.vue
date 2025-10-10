<template>
<v-row justify=center class='fill-center'>
    <v-col xs=12 sm=8 md=4>
        <v-card class="elevation-12">
            <v-toolbar dark color="primary">
                <v-toolbar-title align-center >{{ $t('activation.successTitle') }}</v-toolbar-title>
            </v-toolbar>
            <v-card-text>
                <p class="mt-12 mb-8 text-center">
                {{ $t('activation.successMessage') }}
                </p>
            </v-card-text>

            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn to="/" color="primary">Go</v-btn>
                <v-spacer></v-spacer>
            </v-card-actions>
        </v-card>
    </v-col>
</v-row>
</template>

<script>
export default {
    created() {
        this.$store.commit('navbar', false);
    },
    data: () => ({
    }),
    head() {
        return {
            title: this.$t('activation.successTitle'),
        };
    },
}
</script>

