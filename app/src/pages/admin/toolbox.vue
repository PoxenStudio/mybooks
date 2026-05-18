<template>
  <v-container fluid class="pa-4">
    <v-row class="mb-3" align="center">
      <v-col>
        <span class="text-h5 font-weight-bold">{{ $t('toolbox.pageTitle') }}</span>
        <div class="text-caption grey--text mt-1">{{ $t('toolbox.pageSubtitle') }}</div>
      </v-col>
    </v-row>

    <v-alert v-if="error" type="error" dense class="mb-4">{{ error }}</v-alert>

    <v-row v-if="loading" justify="center" class="py-10">
      <v-progress-circular indeterminate color="primary" size="48" />
    </v-row>

    <v-row v-else-if="tools.length === 0" justify="center" class="py-10">
      <v-col cols="auto" class="text-center grey--text">{{ $t('toolbox.noTools') }}</v-col>
    </v-row>

    <v-row v-else>
      <v-col
        v-for="tool in tools"
        :key="tool.id"
        cols="12"
        md="4"
      >
        <v-card
          class="tool-card pa-2"
          rounded="xl"
          outlined
          @click="goToTool(tool)"
          style="cursor: pointer; border: 2px solid #90CAF9;"
        >
          <v-card-text>
            <div class="d-flex align-center mb-3">
              <v-avatar size="56" rounded="lg" class="mr-3">
                <v-img
                  :src="`/get/tool/${tool.id}/icon`"
                  :alt="tool.name"
                >
                  <template #error>
                    <v-icon size="36" color="primary">mdi-tools</v-icon>
                  </template>
                </v-img>
              </v-avatar>
              <div>
                <div class="text-subtitle-1 font-weight-bold">{{ tool.name }}</div>
                <v-chip x-small color="primary" outlined class="mt-1">v{{ tool.revision }}</v-chip>
              </div>
            </div>
            <div class="text-body-2 grey--text text--darken-1 mb-3" style="min-height: 40px;">
              {{ tool.description }}
            </div>
            <div class="d-flex justify-space-between align-center text-caption grey--text">
              <span><v-icon x-small>mdi-account-outline</v-icon> {{ tool.author }}</span>
              <span v-if="tool.publish_date"><v-icon x-small>mdi-calendar-outline</v-icon> {{ tool.publish_date }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
  </v-container>
</template>

<script>
export default {
  data: () => ({
    tools: [],
    loading: false,
    error: null,
  }),
  head() {
    return { title: this.$t('toolbox.pageTitle') };
  },
  async asyncData({ app, res }) {
    if (res !== undefined) {
      res.setHeader("Cache-Control", "no-cache");
    }
    try {
      const data = await app.$backend("/admin/toolbox/list");
      if (data.err !== "ok") {
        return { tools: [], error: data.msg || "error" };
      }
      return { tools: data.tools || [] };
    } catch (e) {
      return { tools: [], error: String(e) };
    }
  },
  created() {
    this.$store.commit("navbar", true);
  },
  methods: {
    goToTool(tool) {
      let toolPage = tool.page || tool.id;
      this.$router.push(`/toolbox/${toolPage}`);
    },
  },
};
</script>

<style scoped>
.tool-card {
  transition: box-shadow 0.2s, transform 0.2s;
}
.tool-card:hover {
  box-shadow: 0 6px 20px rgba(144, 202, 249, 0.45) !important;
  transform: translateY(-2px);
}
</style>
