<template>
    <v-row justify=center class='fill-center'>
      <v-col xs=12 sm=8 md=4>
        <v-card class="elevation-12">
            <v-toolbar dark color="blue-grey">
                <v-toolbar-title></v-toolbar-title>
            </v-toolbar>
            <v-card-text>
                <div class="text-center title primary--text">
                    <p class="pt-8">{{ $t('logout.message') }}</p>
                </div>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn class="mb-4" rounded color="primary" href="/">{{ $t('logout.homeButton') }}</v-btn>
                <v-spacer></v-spacer>
            </v-card-actions>
        </v-card>
          </v-col>
        </v-row>
</template>

<script>
export default {
    created() {
        this.$store.commit("navbar", false);
        this.logout();
    },
    computed: {
        msg() {
            return this.$t('logout.message'); // Dynamically compute msg using $t
        },
    },
    head() {
        return {
            title: this.$t('logout.pageTitle'),
        };
    },
    methods: {
        logout: function() {
            this.$backend('/user/sign_out')
            .then( rsp => {});
        }
    },
}
</script>

