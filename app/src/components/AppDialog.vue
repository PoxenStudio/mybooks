<template>
    <v-dialog
        v-model="internalValue"
        :persistent="persistent"
        :width="width"
        :max-width="maxWidth"
        :scrollable="scrollable"
        :transition="transition"
    >
        <v-card :class="cardClass" style="border-radius:16px 16px 0px 0px !important">
            <template v-if="type !== 'progress'">
                <!-- Vuetify 的 dark/light 是三态：dark=true 强制白字、light=true 强制深字，都不传才继承根主题。
                     默认（lightHeader=false）等价于原来的裸 dark 属性，行为不变；传了浅色自定义色（如浅色品牌色）
                     的调用方需要传 light-header，否则白字会落在浅底上。 -->
                <v-toolbar flat dense :dark="!lightHeader" :light="lightHeader" :color="color" :class="toolbarClass" style="border-radius:16px 16px 0px 0px !important">
                    <v-icon v-if="icon" class="mr-2">{{ icon }}</v-icon>
                    <v-toolbar-title>{{ title }}</v-toolbar-title>
                    <v-spacer></v-spacer>
                    <v-btn v-if="dismissIcon" icon :dark="!lightHeader" :light="lightHeader" :disabled="dismissDisabled" @click="onDismiss">
                        <v-icon>mdi-close</v-icon>
                    </v-btn>
                    <v-btn v-else text :disabled="dismissDisabled" @click="onDismiss">
                        {{ resolvedDismissLabel }}
                    </v-btn>
                </v-toolbar>
            </template>
            <template v-else-if="title">
                <v-card-title>{{ title }}</v-card-title>
            </template>

            <v-card-text class="pt-4">
                <slot></slot>
            </v-card-text>

            <v-card-actions v-if="$slots.actions">
                <slot name="actions"></slot>
            </v-card-actions>
            <v-card-actions v-else-if="type === 'progress'" class="justify-center">
                <v-btn v-if="!hideFooterButton" text @click="onDismiss">
                    {{ resolvedDismissLabel }}
                </v-btn>
            </v-card-actions>
            <v-card-actions v-else-if="!hideFooterButton" class="justify-center">
                <v-btn
                    :color="confirmColor || color"
                    :dark="confirmDark"
                    :loading="confirmLoading"
                    :disabled="confirmDisabled"
                    @click="$emit('confirm')"
                >
                    <v-icon v-if="confirmIcon" left>{{ confirmIcon }}</v-icon>
                    {{ confirmText }}
                </v-btn>
            </v-card-actions>
        </v-card>
    </v-dialog>
</template>

<script>
// 全站对话框统一骨架，覆盖设计规范中的三种类型：
//   type="action"   功能操作对话框 —— toolbar 右上角取消/关闭，footer 单个执行按钮
//   type="confirm"  提问确认对话框 —— toolbar 右上角取消，footer 单个确认按钮（颜色随 color）
//   type="progress" 进度反馈对话框 —— 不设 toolbar，footer 只保留一个取消按钮
// 规范详见 document/Dialog_Standard_Design.md，速查见 .claude/rules/ui.md
export default {
    name: 'AppDialog',
    props: {
        value: { type: Boolean, default: false },
        title: { type: String, default: '' },
        icon: { type: String, default: '' },
        type: {
            type: String,
            default: 'action',
            validator: (v) => ['action', 'confirm', 'progress'].includes(v),
        },
        color: { type: String, default: 'primary' },
        // 外壳 toolbar 的前景配色：默认走「深色底 / 白字」（与原实现一致）。
        // 传自定义浅色（例如外观设置里用户选的浅色品牌色）时必须置 true，否则白字落在浅底上看不见。
        lightHeader: { type: Boolean, default: false },
        width: { type: [String, Number], default: undefined },
        maxWidth: { type: [String, Number], default: 500 },
        persistent: { type: Boolean, default: true },
        scrollable: { type: Boolean, default: false },
        transition: { type: String, default: undefined },
        // 极少数场景需要给外壳 v-card/v-toolbar 附加自定义 class（如圆角样式），一般不需要传
        cardClass: { type: [String, Array, Object], default: '' },
        toolbarClass: { type: [String, Array, Object], default: '' },
        // 右上角/footer 取消按钮文案；不传时按 type 取默认值（common.cancel，progress 场景外均可用 common.close 覆盖）
        dismissLabel: { type: String, default: '' },
        // 右上角按钮用图标（mdi-close）而不是文字，两者选一，默认用文字
        dismissIcon: { type: Boolean, default: false },
        dismissDisabled: { type: Boolean, default: false },
        // footer 唯一功能按钮（action/confirm 类型）
        confirmText: { type: String, default: '' },
        confirmIcon: { type: String, default: '' },
        confirmColor: { type: String, default: '' },
        // Vuetify 的命名主题色（primary/orange/deep-orange/info/error…）会自动生成白色文字，
        // 但传自定义十六进制色（如 #003153）时不会，字与底色对比度会太低——这种场景传 true 强制走深色底/白字配色
        confirmDark: { type: Boolean, default: false },
        confirmLoading: { type: Boolean, default: false },
        confirmDisabled: { type: Boolean, default: false },
        // 不显示 footer 按钮：progress 类型下用于纯阻塞、不可取消的流程
        hideFooterButton: { type: Boolean, default: false },
    },
    computed: {
        internalValue: {
            get() { return this.value; },
            set(v) { this.$emit('input', v); },
        },
        resolvedDismissLabel() {
            if (this.dismissLabel) return this.dismissLabel;
            return this.$t('common.cancel');
        },
    },
    methods: {
        onDismiss() {
            this.internalValue = false;
            this.$emit('dismiss');
        },
    },
};
</script>
