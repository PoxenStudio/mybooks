<template>
    <div>
        <v-btn
            v-show="showUploadButtons && ($store.state.sys.allow.upload || $store.state.user.is_login)"
            bottom
            color="pink"
            dark
            fab
            fixed
            right
            @click="dialog = !dialog"
            style="z-index: 10; margin-bottom: 80px;"
        >
            <v-icon>mdi-upload</v-icon>
        </v-btn>

        <!-- 添加实体书按钮 -->
        <v-btn
            v-show="showUploadButtons && ($store.state.sys.allow.upload || $store.state.user.is_login) && $store.state.sys.allow.physical_books"
            bottom
            color="green"
            dark
            fab
            fixed
            right
            @click="isbn_dialog = !isbn_dialog"
            style="z-index: 10;"
        >
            <v-icon>mdi-book-plus</v-icon>
        </v-btn>

        <AppDialog
            v-model="dialog"
            type="action"
            :title="$t('upload.title')"
            color="#003153"
            width="360"
            transition="dialog-bottom-transition"
            :dismiss-label="$t('upload.close')"
            :confirm-text="$t('upload.upload')"
            confirm-dark
            :confirm-loading="loading"
            @confirm="do_upload"
        >
            <v-form ref="form" @submit="do_upload">
                <v-file-input
                    v-model="ebooks"
                    multiple
                    show-size
                    counter
                    :label="$t('upload.selectFile')"
                ></v-file-input>
            </v-form>
        </AppDialog>

        <BatchImportDialog
            v-model="batchDialog"
            :import-id="batchImportId"
            :file-count="ebooks.length"
        />


        <!-- 添加实体书对话框 -->
        <AppDialog
            v-if="($store.state.sys.allow.upload || $store.state.user.is_login) && $store.state.sys.allow.physical_books"
            v-model="isbn_dialog"
            type="action"
            :title="$t('upload.addPhysicalBook')"
            icon="mdi-book-plus"
            color="green"
            width="410"
            transition="dialog-bottom-transition"
            card-class="upload-dialog-card"
            toolbar-class="upload-dialog-toolbar"
            :dismiss-label="$t('upload.close')"
            :confirm-text="$t('upload.confirmAdd')"
            confirm-color="green"
            confirm-dark
            :confirm-loading="adding_book"
            :confirm-disabled="!canConfirmAdd"
            @dismiss="cancelAddBook"
            @confirm="confirmAddBook"
        >
                    <v-radio-group v-model="addMode" row hide-details class="mt-0 mb-4">
                        <v-radio :label="$t('upload.modeIsbn')" value="isbn" color="green"></v-radio>
                        <v-radio :label="$t('upload.modeManual')" value="manual" color="green"></v-radio>
                    </v-radio-group>
                    <template v-if="addMode === 'manual'">
                        <p class="body-1">{{ $t('upload.addManualDesc') }}</p>
                        <v-text-field key="manual-title" ref="manualTitleField" v-model="manualTitle" :label="$t('upload.titleLabel')" outlined
                            maxlength="100" counter :rules="manualTitleRules"
                            @keyup.enter="confirmAddBook"></v-text-field>
                        <v-text-field key="manual-isbn" v-model="isbn" :label="$t('upload.isbnOptionalLabel')" outlined
                            maxlength="17" :rules="manualIsbnRules" @keyup.enter="confirmAddBook">
                            <template v-slot:prepend-inner><v-icon>mdi-barcode</v-icon></template>
                        </v-text-field>
                        <v-text-field key="manual-author" v-model="manualAuthor" :label="$t('upload.authorOptionalLabel')" outlined
                            maxlength="64" counter :hint="$t('upload.authorHint')" persistent-hint :rules="manualAuthorRules"
                            @keyup.enter="confirmAddBook"></v-text-field>
                    </template>
                    <template v-else>
                    <p class="body-1">{{ $t('upload.addPhysicalBookDesc') }}</p>
                    <v-text-field
                        key="isbn-field"
                        ref="isbnField"
                        v-model="isbn"
                        :label="$t('upload.isbnLabel')"
                        :placeholder="$t('upload.isbnPlaceholder')"
                        outlined
                        :rules="debouncedIsbnRules"
                        counter
                        maxlength="17"
                        :hint="$t('upload.isbnHint')"
                        persistent-hint
                        @keyup.enter="confirmAddBook"
                        @input="clearValidationCache"
                    >
                        <template v-slot:prepend-inner>
                            <v-icon>mdi-barcode</v-icon>
                        </template>
                        <template v-slot:append>
                            <v-tooltip bottom>
                                <template v-slot:activator="{ on, attrs }">
                                    <v-btn
                                        icon
                                        small
                                        @click="triggerImageUpload"
                                        :loading="recognizing_barcode"
                                        :disabled="recognizing_barcode"
                                        color="primary"
                                        v-bind="attrs"
                                        v-on="on"
                                    >
                                        <v-icon>mdi-camera</v-icon>
                                    </v-btn>
                                </template>
                                <span>{{ $t('upload.selectImageForBarcode') }}</span>
                            </v-tooltip>
                        </template>
                    </v-text-field>

                    </template>

                    <!-- 隐藏的文件输入框 -->
                    <input
                        ref="barcodeImageInput"
                        type="file"
                        accept="image/*"
                        style="display: none"
                        @change="handleImageUpload"
                    />

                    <!-- 继续添加checkbox -->
                    <v-checkbox
                        v-model="continueAdding"
                        :label="$t('upload.continueAdding')"
                        color="green"
                        class="mt-4"
                    ></v-checkbox>
        </AppDialog>
    </div>
</template>

<script>
import BatchImportDialog from '~/components/BatchImportDialog.vue';

export default {
    components: { BatchImportDialog },
    data: () => ({
        loading: false,
        dialog: false,
        // 选择1个文件时按单文件流程处理，选择多个时自动走批量导入流程
        ebooks: [],
        batchDialog: false,
        batchImportId: null,
        // 添加实体书相关数据
        isbn_dialog: false,
        adding_book: false,
        isbn: "",
        addMode: "isbn", // isbn | manual
        manualTitle: "",
        manualAuthor: "",
        continueAdding: false,
        // 条形码识别相关
        recognizing_barcode: false,
        // 防抖相关变量
        shouldValidate: false,
        // 防抖验证规则（由 buildDebouncedIsbnRules() 构建，不放进 computed 是因为它本身
        // 不是"从响应式状态派生"，而是"只构建一次的规则闭包数组"，构建过程里要给
        // shouldValidate 赋值，放进 computed 会触发 vue/no-side-effects-in-computed-properties）
        debouncedIsbnRules: [],
        // 控制是否显示验证错误（仅在点击添加按钮时显示）
        showValidationErrors: false,
    }),
    computed: {
        maxSizeStr() {
            if (process.client) {
                return localStorage.getItem('max_upload_size') || '100MB';
            }
            return '100MB';
        },
        showUploadButtons() {
            // 在音频播放器页面隐藏上传按钮
            return !this.$route.path.startsWith('/audio/');
        },
        manualIsbnRules() {
            return [v => !v || /^([0-9]{9}[0-9Xx]|[0-9]{13})$/.test(v.replace(/[-\s]/g, '')) || this.$t('upload.invalidIsbn')];
        },
        manualTitleRules() {
            return [v => !v || (v.length <= 100 && !/['\p{Cc}]/u.test(v)) || this.$t('upload.invalidTitle')];
        },
        manualAuthorRules() {
            return [v => !v || (v.length <= 64 && !/['\p{Cc}]/u.test(v)) || this.$t('upload.invalidAuthor')];
        },
        canConfirmAdd() {
            if (this.addMode === 'manual') {
                const v = this.isbn.replace(/[-\s]/g, '');
                const t = this.manualTitle.trim();
                const a = this.manualAuthor.trim();
                return !!t && t.length <= 100 && a.length <= 64 && !/['"\p{Cc}]/u.test(t + a) && (!v || /^([0-9]{9}[0-9Xx]|[0-9]{13})$/.test(v));
            }
            return this.isValidIsbn;
        },
        isValidIsbn() {
            // Vue 的 computed 本身已按 this.isbn 做依赖缓存，不需要手动缓存
            if (!this.isbn) {
                return false;
            }
            // 移除连字符和空格
            const cleanIsbn = this.isbn.replace(/[-\s]/g, '');
            // 检查是否为10位或13位数字（可能包含X）
            return /^[0-9]{9}[0-9X]$/.test(cleanIsbn) || /^[0-9]{13}$/.test(cleanIsbn);
        },

        // 基础验证规则
        isbnRules() {
            return [
                v => !!v || this.$t('upload.isbnRequired'),
                v => (v && v.length >= 10) || this.$t('upload.isbnMinLength'),
                v => (v && /^[0-9\-X]+$/.test(v)) || this.$t('upload.isbnInvalidFormat'),
            ];
        },
    },
    watch: {
        dialog(val) {
            if (val) {
                // 每次重新打开上传对话框时清空上一次的选择，避免残留旧文件
                this.ebooks = [];
            }
        },
        // 添加实体书对话框：dialog 过渡完成后再聚焦对应字段，避免 Vuetify 的
        // setLabelWidth() 在元素尚未稳定时测量出错误宽度，导致浮动标签位置偏移。
        isbn_dialog(val) {
            if (val) {
                this.$nextTick(() => {
                    setTimeout(() => this.focusAddBookField(), 250);
                });
            }
        },
        addMode() {
            if (this.isbn_dialog) {
                this.$nextTick(() => {
                    setTimeout(() => this.focusAddBookField(), 150);
                });
            }
        },
    },
    created() {
        this.buildDebouncedIsbnRules();
    },
    methods: {
        // 根据当前模式聚焦对应的输入框。延迟调用是为了避开 dialog 的进入过渡，
        // 让 Vuetify 的 setLabelWidth() 在元素稳定后再测量，避免浮动标签位置偏移。
        focusAddBookField() {
            if (this.addMode === 'manual') {
                this.$refs.manualTitleField && this.$refs.manualTitleField.focus();
            } else {
                this.$refs.isbnField && this.$refs.isbnField.focus();
            }
        },
        // 构建防抖验证规则（原来放在 computed 里"只构建一次"，会在计算过程中
        // 给 shouldValidate 赋值触发 vue/no-side-effects-in-computed-properties；
        // 挪到普通方法里，在 created() 里建一次，需要重置时显式调用即可）。
        buildDebouncedIsbnRules() {
            const debounce = (func, wait) => {
                let timeout;
                return function executedFunction(...args) {
                    const later = () => {
                        clearTimeout(timeout);
                        func.apply(this, args);
                    };
                    clearTimeout(timeout);
                    timeout = setTimeout(later, wait);
                };
            };

            const validateWithDebounce = debounce(() => {
                this.shouldValidate = true;
                this.$nextTick(() => {
                    this.$refs.isbnField && this.$refs.isbnField.validate();
                });
            }, 300);

            this.debouncedIsbnRules = [
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    if (!this.shouldValidate && v) {
                        validateWithDebounce();
                        return true; // 暂时通过验证，等待防抖完成
                    }
                    return !!v || this.$t('upload.isbnRequired');
                },
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    if (!this.shouldValidate && v) {
                        return true; // 暂时通过验证，等待防抖完成
                    }
                    return (v && v.length >= 10) || this.$t('upload.isbnMinLength');
                },
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    if (!this.shouldValidate && v) {
                        return true; // 暂时通过验证，等待防抖完成
                    }
                    return (v && /^[0-9\-X]+$/.test(v)) || this.$t('upload.isbnInvalidFormat');
                },
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    if (!this.shouldValidate && v) {
                        return true; // 暂时通过验证，等待防抖完成
                    }
                    return this.isValidIsbn || this.$t('upload.invalidIsbn');
                },
            ];
        },
        async do_upload() {
            // 未选择文件
            if (!this.ebooks || this.ebooks.length === 0) {
                this.$alert("error", this.$t('upload.selectFile'));
                return;
            }

            // 选择了多个文件，走批量导入流程
            if (this.ebooks.length > 1) {
                return this.do_batch_upload();
            }

            this.loading = true;
            const file = this.ebooks[0];

            // Get chunk upload threshold from localStorage or server config
            const chunkThresholdStr = localStorage.getItem('chunk_upload_size') || '0MB';
            const chunkThreshold = this.parseSizeString(chunkThresholdStr);

            // If file size exceeds threshold and chunking is enabled, use chunked upload
            if (chunkThreshold > 0 && file.size > chunkThreshold) {
                await this.do_chunked_upload(file, chunkThreshold);
            } else {
                await this.do_regular_upload(file);
            }
        },

        async do_regular_upload(file) {
            try {
                const data = new FormData();
                data.append("ebook", file);

                const rsp = await this.$backend("/book/upload", {
                    method: 'POST',
                    body: data,
                });

                this.dialog = false;
                this.handleUploadResponse(rsp);
            } catch (error) {
                const msg = error.message ? this.$t('upload.uploadFailed') + ": " + error.message : this.$t('upload.uploadFailedDetail');
                this.$alert("error", msg);
            } finally {
                this.loading = false;
            }
        },

        async do_chunked_upload(file, chunkSize) {
            try {
                const totalChunks = Math.ceil(file.size / chunkSize);

                // Generate file hash for unique identification
                const fileHash = await this.generateFileHash(file);

                // Upload chunks sequentially
                for (let i = 0; i < totalChunks; i++) {
                    const start = i * chunkSize;
                    const end = Math.min(start + chunkSize, file.size);
                    const chunk = file.slice(start, end);

                    const formData = new FormData();
                    formData.append("chunk", chunk);
                    formData.append("filename", file.name);
                    formData.append("chunk_index", i.toString());
                    formData.append("total_chunks", totalChunks.toString());
                    formData.append("file_hash", fileHash);

                    const rsp = await this.$backend("/book/upload/chunk", {
                        method: 'POST',
                        body: formData,
                    });

                    if (rsp.err !== 'ok') {
                        throw new Error(rsp.msg || this.$t('upload.chunkUploadFailed'));
                    }

                    // Update progress (this is the final chunk response)
                    if (i === totalChunks - 1) {
                        this.dialog = false;
                        this.handleUploadResponse(rsp);
                        return;
                    }
                }
            } catch (error) {
                const msg = error.message ? this.$t('upload.chunkUploadFailed') + ": " + error.message : this.$t('upload.uploadFailedDetail');
                this.$alert("error", msg);
            } finally {
                this.loading = false;
            }
        },

        handleUploadResponse(rsp) {
            if (rsp.err === 'ok') {
                this.$alert("success", this.$t('upload.uploadSuccess'), "/book/" + rsp.book_id);
                this.$router.push("/book/" + rsp.book_id);
            } else if (rsp.err === 'samebook') {
                this.$alert("error", rsp.msg, "/book/" + rsp.book_id);
                this.$router.push("/book/" + rsp.book_id);
            } else {
                this.$alert("error", rsp.msg);
            }
        },

        // 多文件批量上传：暂存到服务器后触发扫描导入，弹出进度对话框轮询逐文件结果
        async do_batch_upload() {
            this.loading = true;
            try {
                const data = new FormData();
                this.ebooks.forEach((file) => {
                    data.append("ebooks", file, file.name);
                    // 当前只支持多文件选择(无目录结构)，相对路径统一留空，后端会退化为使用文件名
                    data.append("relative_paths", "");
                });

                const rsp = await this.$backend("/book/upload/batch", {
                    method: 'POST',
                    body: data,
                });

                if (rsp.err !== 'ok') {
                    this.$alert("error", rsp.msg || this.$t('upload.batchStartFailed'));
                    return;
                }

                this.dialog = false;
                this.batchImportId = rsp.import_id;
                this.batchDialog = true;
            } catch (error) {
                const msg = error.message ? this.$t('upload.batchStartFailed') + ": " + error.message : this.$t('upload.batchStartFailed');
                this.$alert("error", msg);
            } finally {
                this.loading = false;
                this.ebooks = [];
            }
        },

        parseSizeString(sizeStr) {
            if (!sizeStr || sizeStr === "0" || sizeStr === "0MB" || sizeStr === "0KB") {
                return 0;
            }

            const size = sizeStr.toLowerCase().trim();
            if (size.endsWith("mb")) {
                return parseInt(size.slice(0, -2)) * 1024 * 1024;
            } else if (size.endsWith("kb")) {
                return parseInt(size.slice(0, -2)) * 1024;
            } else {
                return parseInt(size);
            }
        },

        async generateFileHash(file) {
            // Simple hash based on file name, size, and first few bytes
            const firstChunk = file.slice(0, 1024);
            const arrayBuffer = await firstChunk.arrayBuffer();
            const uint8Array = new Uint8Array(arrayBuffer);

            let hash = 0;
            const str = file.name + file.size + Array.from(uint8Array).join('');
            for (let i = 0; i < str.length; i++) {
                const char = str.charCodeAt(i);
                hash = ((hash << 5) - hash) + char;
                hash = hash & hash; // Convert to 32-bit integer
            }
            return Math.abs(hash).toString(16);
        },

        cancelAddBook() {
            this.isbn_dialog = false;
            this.isbn = "";
            this.manualTitle = "";
            this.manualAuthor = "";
            this.addMode = "isbn";
            this.continueAdding = false; // 重置checkbox状态
            // 重置验证状态
            this.showValidationErrors = false;
            this.shouldValidate = false;
            this.buildDebouncedIsbnRules();
        },

        confirmAddBook() {
            if (this.addMode === 'manual') {
                this.confirmAddManual();
                return;
            }
            // 触发验证显示
            this.showValidationErrors = true;
            this.shouldValidate = true;

            // 等待下一个tick让验证生效，然后检查表单有效性
            this.$nextTick(() => {
                // 重新计算验证规则
                this.buildDebouncedIsbnRules();

                // 手动验证字段
                if (this.$refs.isbnField) {
                    this.$refs.isbnField.validate();
                }

                // 检查ISBN是否有效
                if (!this.isbn) {
                    this.$alert("error", this.$t('upload.isbnRequired'));
                    return;
                }

                if (!this.isValidIsbn) {
                    this.$alert("error", this.$t('upload.invalidIsbn'));
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
                        // 如果勾选了继续添加，则跳转时携带参数
                        if (this.continueAdding) {
                            this.$router.push(`/book/${rsp.book_id}?continue_adding=true`);
                        } else {
                            this.$alert("success", rsp.msg || this.$t('upload.addSuccess'));
                            this.$router.push(`/book/${rsp.book_id}`);
                        }
                    }
                })
                .catch((error) => {
                    const msg = error.message ? this.$t('upload.addBookError') + ": " + error.message : this.$t('upload.addBookError');
                    this.$alert("error", msg);
                })
                .finally(() => {
                    this.adding_book = false;
                    this.isbn = "";
                    // 只有在不继续添加的情况下才重置checkbox
                    if (!this.continueAdding) {
                        this.continueAdding = false;
                    }
                });
            });
        },

        confirmAddManual() {
            if (!this.canConfirmAdd || this.adding_book) {
                return;
            }
            this.adding_book = true;
            this.$backend("/book/add/manual", {
                method: "POST",
                body: JSON.stringify({
                    title: this.manualTitle.trim(),
                    author: this.manualAuthor.trim(),
                    isbn: this.isbn.replace(/[-\s]/g, ''),
                }),
            })
            .then((rsp) => {
                if (rsp.err != "ok") {
                    this.$alert("error", rsp.msg);
                    return;
                }
                this.isbn_dialog = false;
                if (this.continueAdding) {
                    this.$router.push(`/book/${rsp.book_id}?continue_adding=true`);
                } else {
                    this.$alert("success", rsp.msg || this.$t('upload.addSuccess'));
                    this.$router.push(`/book/${rsp.book_id}`);
                }
                this.isbn = "";
                this.manualTitle = "";
                this.manualAuthor = "";
            })
            .catch((error) => {
                const msg = error.message ? this.$t('upload.addBookError') + ": " + error.message : this.$t('upload.addBookError');
                this.$alert("error", msg);
            })
            .finally(() => {
                this.adding_book = false;
            });
        },

        // 清除验证缓存，重置防抖状态
        clearValidationCache() {
            this.shouldValidate = false;
            // 如果用户开始重新输入，重置验证错误显示状态
            if (this.isbn && this.showValidationErrors) {
                this.showValidationErrors = false;
                this.buildDebouncedIsbnRules();
            }
        },

        // 触发图片上传
        triggerImageUpload() {
            this.$refs.barcodeImageInput.click();
        },

        // 处理图片上传和条形码识别
        handleImageUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            // 检查文件类型
            if (!file.type.startsWith('image/')) {
                this.$alert("error", this.$t('upload.invalidImageType'));
                return;
            }

            // 检查文件大小（限制为10MB）
            if (file.size > 10 * 1024 * 1024) {
                this.$alert("error", this.$t('upload.imageTooLarge'));
                return;
            }

            this.recognizing_barcode = true;

            // 创建FormData对象
            const formData = new FormData();
            formData.append('barcode_image', file);

            // 调用后端API识别条形码
            this.$backend('/admin/barcode', {
                method: 'POST',
                body: formData,
            })
            .then(response => {
                if (response.err === 'ok') {
                    // 识别成功，填充ISBN字段
                    this.isbn = response.isbn;
                    // 清除验证状态，触发重新验证
                    this.clearValidationCache();
                    this.shouldValidate = true;
                    this.$nextTick(() => {
                        this.$refs.isbnField && this.$refs.isbnField.validate();
                    });
                } else if (response.err === 'no_barcode') {
                    this.$alert("error", this.$t('upload.noBarcodeFound'));
                } else if (response.err === 'no_isbn') {
                    this.$alert("warning", response.msg);
                } else {
                    this.$alert("error", response.msg || this.$t('upload.barcodeRecogizedFailed'));
                }
            })
            .catch(error => {
                console.error('Failed to recognize barcode:', error);
                this.$alert("error", this.$t('upload.barcodeRecognitionFailed'));
            })
            .finally(() => {
                this.recognizing_barcode = false;
                // 清空文件输入框，允许重复选择同一文件
                event.target.value = '';
            });
        },
    },

}
</script>

<style scoped>
/* Vuetify 的 outlined text-field 在聚焦时会给 fieldset > legend 设置 width
   来制造"缺口"效果，浮动标签就放在缺口里。这个 width 由 setLabelWidth() 计算，
   如果在 dialog 过渡期间测量（element 尚未稳定），结果会是 0，缺口就消失了。
   这里给 legend 加一个最小宽度，作为时序竞态下的安全网。 */
::v-deep .v-text-field--outlined > .v-input__control > .v-input__slot > fieldset > legend {
    min-width: 48px;
}
</style>
