<template>
    <div>
        <v-btn bottom color="pink" dark fab fixed right @click="dialog = !dialog" style="z-index: 10; margin-bottom: 80px;">
            <v-icon>mdi-upload</v-icon>
        </v-btn>

        <!-- 添加实体书按钮 -->
        <v-btn bottom color="green" dark fab fixed right @click="isbn_dialog = !isbn_dialog" style="z-index: 10;">
            <v-icon>mdi-book-plus</v-icon>
        </v-btn>

        <v-dialog v-model="dialog" persistent transition="dialog-bottom-transition" width="300">
            <v-card>
                <v-toolbar flat dense dark color="primary">
                    {{ $t('upload.title') }}
                    <v-spacer></v-spacer>
                    <v-btn color="" text @click="dialog = false">{{ $t('upload.close') }}</v-btn>
                </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p>{{ $t('upload.warning', { max_size: maxSizeStr}) }}</p>
                    <v-form ref="form" @submit="do_upload">
                        <v-file-input v-model="ebooks" :label="$t('upload.selectFile')"></v-file-input>
                    </v-form>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn :loading="loading" color="primary" @click="do_upload">{{ $t('upload.upload') }}</v-btn>
                    <v-spacer></v-spacer>
                </v-card-actions>
            </v-card>
        </v-dialog>

        <!-- 添加实体书对话框 -->
        <v-dialog v-model="isbn_dialog" persistent transition="dialog-bottom-transition" width="400">
            <v-card>
                <v-toolbar flat dense dark color="green">
                    <v-icon>mdi-book-plus</v-icon>
                    <v-toolbar-title class="ml-2">{{ $t('upload.addPhysicalBook') }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn color="" text @click="cancelAddBook">{{ $t('upload.close') }}</v-btn>
                </v-toolbar>
                <v-card-title></v-card-title>
                <v-card-text>
                    <p class="body-1">{{ $t('upload.addPhysicalBookDesc') }}</p>
                    <v-text-field
                        v-model="isbn"
                        :label="$t('upload.isbnLabel')"
                        :placeholder="$t('upload.isbnPlaceholder')"
                        outlined
                        :rules="isbnRules"
                        counter
                        maxlength="17"
                        :hint="$t('upload.isbnHint')"
                        persistent-hint
                        autofocus
                        @keyup.enter="confirmAddBook"
                    >
                        <template v-slot:prepend-inner>
                            <v-icon>mdi-barcode</v-icon>
                        </template>
                    </v-text-field>

                    <!-- 继续添加checkbox -->
                    <v-checkbox
                        v-model="continueAdding"
                        :label="$t('upload.continueAdding')"
                        color="green"
                        class="mt-4"
                    ></v-checkbox>
                </v-card-text>
                <v-card-actions>
                    <v-spacer></v-spacer>
                    <v-btn
                        :loading="adding_book"
                        color="green"
                        @click="confirmAddBook"
                        :disabled="!isValidIsbn"
                    >
                        {{ $t('upload.confirmAdd') }}
                    </v-btn>
                    <v-spacer></v-spacer>
                </v-card-actions>
            </v-card>
        </v-dialog>
    </div>
</template>

<script>
export default {
    data: () => ({
        loading: false,
        dialog: false,
        ebooks: null,
        // 添加实体书相关数据
        isbn_dialog: false,
        adding_book: false,
        isbn: "",
        continueAdding: false,
        isbnRules: [
            v => !!v || 'ISBN号不能为空',
            v => (v && v.length >= 10) || 'ISBN号至少需要10位',
            v => (v && /^[0-9\-X]+$/.test(v)) || 'ISBN号只能包含数字、连字符和X',
        ],
    }),
    computed: {
        maxSizeStr() {
            if (process.client) {
                return localStorage.getItem('max_upload_size') || '100MB';
            }
            return '100MB';
        },
        isValidIsbn() {
            if (!this.isbn) return false;
            // 移除连字符和空格
            const cleanIsbn = this.isbn.replace(/[-\s]/g, '');
            // 检查是否为10位或13位数字（可能包含X）
            return /^[0-9]{9}[0-9X]$/.test(cleanIsbn) || /^[0-9]{13}$/.test(cleanIsbn);
        }
    },
    methods: {
        do_upload: function () {
            this.loading = true;
            var data = new FormData();
            data.append("ebook", this.ebooks);
            this.$backend("/book/upload", {
                method: 'POST',
                body: data,
            })
                .then(rsp => {
                    this.dialog = false;
                    if (rsp.err === 'ok') {
                        this.$alert("success", "上传成功！", "/book/" + rsp.book_id);
                        this.$router.push("/book/" + rsp.book_id)
                    } else if (rsp.err === 'samebook') {
                        this.$alert("error", rsp.msg, "/book/" + rsp.book_id);
                        this.$router.push("/book/" + rsp.book_id)
                    } else {
                        this.$alert("error", rsp.msg);
                    }
                })
                .finally(() => {
                    this.loading = false;
                });
        },

        cancelAddBook() {
            this.isbn_dialog = false;
            this.isbn = "";
            this.continueAdding = false; // 重置checkbox状态
        },

        confirmAddBook() {
            if (!this.isValidIsbn) {
                this.$alert("error", "请输入有效的ISBN号");
                return;
            }

            this.adding_book = true;
            // 清理ISBN号（移除连字符和空格）
            const cleanIsbn = this.isbn.replace(/[-\s]/g, '');

            this.$backend("/book/add", {
                method: "POST",
                body: JSON.stringify({
                    isbn: cleanIsbn,
                }),
            })
            .then((rsp) => {
                this.isbn_dialog = false;
                if (rsp.err != "ok") {
                    this.$alert("error", rsp.msg);
                } else {
                    this.$alert("success", rsp.msg || "图书添加成功");

                    // 如果勾选了继续添加，则跳转时携带参数
                    if (this.continueAdding) {
                        this.$router.push(`/book/${rsp.book_id}?continue_adding=true`);
                    } else {
                        this.$router.push(`/book/${rsp.book_id}`);
                    }
                }
            })
            .catch((error) => {
                this.$alert("error", "添加图书时发生错误: " + error.message);
            })
            .finally(() => {
                this.adding_book = false;
                this.isbn = "";
                // 只有在不继续添加的情况下才重置checkbox
                if (!this.continueAdding) {
                    this.continueAdding = false;
                }
            });
        },
    },

}
</script>

