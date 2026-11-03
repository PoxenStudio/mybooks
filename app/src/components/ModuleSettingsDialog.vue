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
        <v-checkbox
            v-for="mod in moduleDefs"
            :key="mod.id"
            :input-value="local[mod.id]"
            :label="$t(mod.label)"
            hide-details
            dense
            class="mb-2"
            @change="onToggle(mod.id, $event)"
        ></v-checkbox>
    </AppDialog>
</template>

<script>
const MODULE_DEFS = [
    { id: "multiuser", label: "settings.enable_module_multiuser" },
    { id: "community", label: "settings.enable_module_community" },
    { id: "audio", label: "settings.enable_module_audio" },
    { id: "physical", label: "settings.enable_module_physical" },
    { id: "ai", label: "settings.enable_module_ai" },
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
