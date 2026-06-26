<template>
    <v-menu v-model="menu" :close-on-content-click="false" offset-y bottom left min-width="320" max-width="320">
        <template v-slot:activator="{ on, attrs }">
            <v-btn icon v-bind="attrs" v-on="on" title="外观设置 (Appearance)">
                <v-icon>mdi-palette-outline</v-icon>
            </v-btn>
        </template>
        <v-card class="appearance-menu-card">
            <v-card-title class="subtitle-2 font-weight-bold pb-2 pt-4">APPEARANCE</v-card-title>
            <v-card-text>
                <!-- Theme Mode -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">Theme</div>
                    <v-btn-toggle v-model="settings.darkMode" mandatory dense class="w-100 d-flex" @change="applySettings">
                        <v-btn :value="false" class="flex-grow-1" small>
                            <v-icon left small>mdi-white-balance-sunny</v-icon> Light
                        </v-btn>
                        <v-btn :value="true" class="flex-grow-1" small>
                            <v-icon left small>mdi-weather-night</v-icon> Dark
                        </v-btn>
                    </v-btn-toggle>
                </div>

                <!-- Accent Colors -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">Accent</div>
                    <div class="d-flex flex-wrap" style="gap: 8px;">
                        <div 
                            v-for="color in accentColors" 
                            :key="color.value"
                            class="color-swatch"
                            :style="{ backgroundColor: color.value }"
                            :class="{ 'selected-swatch': settings.accent === color.value }"
                            @click="selectAccent(color.value)"
                        >
                            <v-icon v-if="settings.accent === color.value" small color="white" style="text-shadow: 0 1px 2px rgba(0,0,0,0.5);">mdi-check</v-icon>
                        </div>
                    </div>
                </div>

                <!-- Radius -->
                <div class="mb-4">
                    <div class="caption text--secondary mb-2">Radius</div>
                    <v-btn-toggle v-model="settings.radius" mandatory dense class="w-100 d-flex" @change="applySettings">
                        <v-btn v-for="r in radiusOptions" :key="r.value" :value="r.value" class="flex-grow-1" small>
                            {{ r.label }}
                        </v-btn>
                    </v-btn-toggle>
                </div>

                <!-- Background Pattern -->
                <div class="mb-2">
                    <div class="caption text--secondary mb-2">Background</div>
                    <div class="bg-name-grid">
                        <v-btn
                            v-for="bg in bgOptions"
                            :key="bg.value"
                            x-small
                            depressed
                            :color="settings.background === bg.value ? 'primary' : ''"
                            :class="settings.background === bg.value ? 'white--text' : 'bg-name-btn'"
                            @click="selectBackground(bg.value)"
                        >{{ bg.label }}</v-btn>
                    </div>
                </div>
            </v-card-text>
        </v-card>
    </v-menu>
</template>

<script>
export default {
    name: 'AppearanceMenu',
    data() {
        return {
            menu: false,
            settings: {
                darkMode: true, // Default to dark mode
                accent: '#1976D2', // Vuetify default primary
                radius: '4px',
                background: 'default'
            },
            accentColors: [
                { value: '#1976D2', name: 'Blue' },
                { value: '#E91E63', name: 'Pink' },
                { value: '#9C27B0', name: 'Purple' },
                { value: '#4CAF50', name: 'Green' },
                { value: '#FF9800', name: 'Orange' },
                { value: '#607D8B', name: 'Blue Grey' },
                { value: '#009688', name: 'Teal' },
                { value: '#F44336', name: 'Red' },
            ],
            radiusOptions: [
                { label: '0', value: '0px' },
                { label: '0.25', value: '4px' },
                { label: '0.5', value: '8px' },
                { label: '1.0', value: '16px' },
            ],
            bgOptions: [
                // Fundamental
                { label: 'None',       value: 'default' },
                { label: 'Dots',       value: 'dots' },
                { label: 'Cross',      value: 'cross' },
                { label: 'Left',       value: 'left-diagonal' },
                // Structural
                { label: 'Blueprint',  value: 'blueprint' },
                { label: 'Right',      value: 'right-diagonal' },
                { label: 'Carbon',     value: 'carbon' },
                { label: 'Perforated', value: 'perforated' },
                // Gradient / Ambient
                { label: 'Aurora',     value: 'aurora' },
                { label: 'Horizon',    value: 'horizon' },
                { label: 'Glow',       value: 'glow' },
                { label: 'Mesh',       value: 'mesh' }
            ]
        };
    },
    mounted() {
        this.loadSettings();
        // Since vuetify instance might be created after our settings, make sure we apply after a small tick
        this.$nextTick(() => {
            this.applySettings(false);
        });
    },
    methods: {
        selectAccent(color) {
            this.settings.accent = color;
            this.applySettings();
        },
        selectBackground(value) {
            this.settings.background = value;
            this.applySettings();
        },
        loadSettings() {
            try {
                const saved = localStorage.getItem('appearance_settings');
                if (saved) {
                    this.settings = { ...this.settings, ...JSON.parse(saved) };
                }
            } catch (e) {
                console.error("Could not load appearance settings", e);
            }
        },
        saveSettings() {
            try {
                localStorage.setItem('appearance_settings', JSON.stringify(this.settings));
            } catch (e) {
                console.error("Could not save appearance settings", e);
            }
        },
        applySettings(save = true) {
            if (save) {
                this.saveSettings();
            }

            // Apply Theme Mode
            this.$vuetify.theme.dark = this.settings.darkMode;

            // Sync --dot-color for background patterns
            const dotColor = this.settings.darkMode
                ? 'rgba(255, 255, 255, 0.12)'
                : 'rgba(0, 0, 0, 0.12)';
            document.documentElement.style.setProperty('--dot-color', dotColor);
            // Sync --primary-color for gradient patterns
            document.documentElement.style.setProperty('--primary-color', this.settings.accent);

            // Apply Accent Color
            this.$vuetify.theme.themes.light.primary = this.settings.accent;
            this.$vuetify.theme.themes.dark.primary = this.settings.accent;

            // Apply Radius via CSS Variable
            document.documentElement.style.setProperty('--app-radius', this.settings.radius);

            // Apply Background Pattern
            document.documentElement.setAttribute('data-bg-pattern', this.settings.background);
        }
    }
};
</script>

<style scoped>
.color-swatch {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.1s ease;
}
.color-swatch:hover {
    transform: scale(1.1);
}
.selected-swatch {
    box-shadow: 0 0 0 2px var(--v-background-base, #fff), 0 0 0 4px currentColor;
}

.bg-name-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 6px;
}
.bg-name-grid .v-btn {
    min-width: 0;
    padding: 0 2px !important;
    font-size: 10px;
}
</style>

