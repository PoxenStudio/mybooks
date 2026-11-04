<template>
    <AppDialog
        :value="value"
        type="action"
        :title="$t('settings.module_dialog_title')"
        icon="mdi-puzzle-outline"
        color="#003153"
        max-width="560"
        :persistent="false"
        dismiss-icon
        :confirm-text="$t('settings.module_dialog_save')"
        @input="$emit('input', $event)"
        @confirm="confirm"
    >
        <div v-for="mod in moduleDefs" :key="mod.id" class="mb-3">
            <v-checkbox
                :input-value="local[mod.id]"
                :label="$t(mod.label)"
                hide-details
                dense
                class="mt-0"
                @change="onToggle(mod.id, $event)"
            ></v-checkbox>
            <div class="text-caption grey--text ml-8">{{ $t(mod.tips) }}</div>
        </div>
    </AppDialog>
</template>

<script>
const MODULE_DEFS = [
    { id: "multiuser", label: "settings.enable_module_multiuser", tips: "settings.enable_module_multiuser_tips" },
    { id: "community", label: "settings.enable_module_community", tips: "settings.enable_module_community_tips" },
    { id: "shared_reading", label: "settings.enable_module_shared_reading", tips: "settings.enable_module_shared_reading_tips" },
    { id: "audio", label: "settings.enable_module_audio", tips: "settings.enable_module_audio_tips" },
    { id: "physical", label: "settings.enable_module_physical", tips: "settings.enable_module_physical_tips" },
    { id: "ai", label: "settings.enable_module_ai", tips: "settings.enable_module_ai_tips" },
];

export default {
    name: "ModuleSettingsDialog",
    props: {
        value: { type: Boolean, default: false },
        storedModules: { type: Object, default: () => ({}) },
    },
    data() {
        return {
            moduleDefs: MODULE_DEFS,
            local: { ...this.storedModules },
        };
    },
    watch: {
        value(open) {
            if (open) {
                this.local = { ...this.storedModules };
            }
        },
        storedModules: {
            deep: true,
            handler() {
                if (this.value) {
                    this.local = { ...this.storedModules };
                }
            },
        },
    },
    methods: {
        onToggle(id, checked) {
            this.$set(this.local, id, checked);
        },
        confirm() {
            this.$emit("confirm", { ...this.local });
        },
    },
};
</script>
