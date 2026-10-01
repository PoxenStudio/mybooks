<template>
    <v-app>
        <loading/>
        <client-only>
            <app-header v-if="$store.state.nav"></app-header>
        </client-only>
        <v-main>
            <v-container fluid>
                <app-press v-if="$store.state.nav"></app-press>
                <Nuxt/>
                <app-footer v-if="$store.state.nav"></app-footer>
            </v-container>

            <v-dialog v-model="$store.state.alert.show" persistent :width="$vuetify.breakpoint.smAndDown?'80%':'40%'">
                <v-card>
                    <div class="blue" style="height:36px"></div>
                    <v-card-text class="pt-6">
                        <v-alert outlined v-model="$store.state.alert.show" :type="$store.state.alert.type">
                            <span v-html="$store.state.alert.msg"></span>
                        </v-alert>
                    </v-card-text>
                    <v-card-actions v-if="$store.state.alert.type!=='success' || $store.state.alert.to">
                        <v-spacer></v-spacer>
                        <v-btn v-if='$store.state.alert.to' color="primary"
                               @click="$router.push($store.state.alert.to);$store.commit('close_alert')">{{ $t('common.ok') }}
                        </v-btn>
                        <v-btn v-else color="primary" @click="$store.commit('close_alert')">{{ $t('common.close') }}</v-btn>
                        <v-spacer></v-spacer>
                    </v-card-actions>
                </v-card>
            </v-dialog>
        </v-main>
        <upload v-if="$store.state.nav"></upload>
    </v-app>
</template>

<script>
import AppHeader from "~/components/AppHeader.vue"
import AppFooter from "~/components/AppFooter.vue"
import AppPress from "~/components/AppPress.vue"
import Loading from "~/components/Loading.vue"
import Upload from "~/components/Upload.vue"

export default {
    name: 'DefaultLayout',
    components: {
        AppHeader,
        AppFooter,
        AppPress,
        Loading,
        Upload,
    },
    data: () => ({}),
    head() {
        return {
            title: this.$store.state.site_title,
            titleTemplate: this.$store.state.site_title_template,
        }
    },
    mounted() {
        this.$store.commit("loaded");
    },
}
</script>
