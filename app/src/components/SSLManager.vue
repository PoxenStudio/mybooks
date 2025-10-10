<template>
    <div>
        <v-btn dense @click="dialog = !dialog" >
            <v-icon>mdi-upload</v-icon> {{ $t('sslManager.updateCertificate') }}
        </v-btn>
        <v-dialog v-model="dialog" persistent transition="dialog-bottom-transition" width="400">
            <v-card>
                <v-toolbar flat dense dark color="primary">
                    {{ $t('sslManager.uploadCertificate') }}
                    <v-spacer></v-spacer>
                    <v-btn color="" text @click="dialog = false">{{ $t('sslManager.close') }}</v-btn>
                </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p>{{ $t('sslManager.instructions') }}</p>
                    <v-form ref="form" @submit="upload_ssl">
                        <v-file-input v-model="ssl_crt" accept=".crt" :label="$t('sslManager.selectCertificateFile')"></v-file-input>
                        <v-file-input v-model="ssl_key" accept=".key" :label="$t('sslManager.selectPrivateKeyFile')"></v-file-input>
                    </v-form>
                </v-card-text>
                <v-card-actions >
                    <v-spacer> </v-spacer>
                    <v-btn :loading="loading" color="primary" @click="upload_ssl">{{ $t('sslManager.uploadCertificate') }}</v-btn>
                    <v-spacer> </v-spacer>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
export default {
    name: "ssl-manager",
    data: () => ({
        loading: false,
        dialog: false,
        ssl_crt: null,
        ssl_key: null,
    }),
    methods: {
        async check_certs() {
            var re = {
                crt: /-----BEGIN CERTIFICATE-----[^ ]*-----END CERTIFICATE-----/gm,
                key: /-----BEGIN [A-Z]* PRIVATE KEY-----[^ ]*-----END [A-Z]* PRIVATE KEY-----/gm,
            };

            var content = await this.ssl_crt.text();
            if ( ! re.crt.test(content) ) {
                this.$alert("error", this.$t('sslManager.invalidCertificateFile'));
                return false;
            }

            var content = await this.ssl_key.text();
            if ( ! re.key.test(content) ) {
                this.loading = false;
                this.$alert("error", this.$t('sslManager.invalidPrivateKeyFile'));
                return false;
            }
            return true;
        },

        async upload_ssl() {
            this.loading = true;
            var ok = await this.check_certs();
            
            if ( !ok ) {
                this.loading = false;
                this.dialog = false;
                return;
            }

            var data = new FormData();
            data.append("ssl_crt", this.ssl_crt);
            data.append("ssl_key", this.ssl_key);
            this.$backend("/admin/ssl", {
                method: 'POST',
                body: data,
            })
            .then( rsp => {
                this.dialog = false;
                if ( rsp.err == 'ok' ) {
                    this.$alert("success", this.$t('sslManager.uploadSuccess'));
                } else {
                    this.$alert("error", rsp.msg);
                }
            })
            .finally(() => {
                this.loading = false;
            });
        },
    },

}
</script>

