<template>
  <div>
    <v-row>
      <v-col cols="12" class="d-flex align-center flex-wrap">
        <v-chip :outlined="!!path" color="amber darken-3" :dark="!path" class="mr-1" @click="goTo('')">
          <v-icon>mdi-home</v-icon>
        </v-chip>
        <template v-for="(crumb, idx) in crumbs">
          <v-icon :key="'sep' + idx" small>mdi-chevron-right</v-icon>
          <v-chip
            :key="crumb.path"
            :outlined="idx < crumbs.length - 1"
            color="amber darken-3"
            :dark="idx === crumbs.length - 1"
            class="mx-1"
            @click="goTo(crumb.path)"
          >
            {{ crumb.name }}
          </v-chip>
        </template>
        <v-btn v-if="isAdmin && path" icon small :title="$t('folder.rename')" @click="openRename">
          <v-icon small>mdi-pencil</v-icon>
        </v-btn>
        <v-divider class="mt-3 mb-0 mx-2"></v-divider>
      </v-col>

      <v-col v-if="subFolders.length" cols="12">
        <v-chip
          v-for="item in subFolders"
          :key="item.name"
          large
          label
          outlined
          color="amber darken-3"
          class="mr-2 mb-2"
          @click="goTo(childPath(item.name))"
        >
          <v-icon left>mdi-folder</v-icon>
          {{ item.name }}
          <span class="ml-2 grey--text">{{ item.count }}</span>
        </v-chip>
      </v-col>

      <v-col v-if="books.length" cols="12">
        <book-cards :books="books"></book-cards>
      </v-col>
      <v-col v-else-if="loaded && !subFolders.length" cols="12" class="text-center grey--text py-8">
        {{ $t('folder.empty') }}
      </v-col>

      <v-col cols="12">
        <v-container class="max-width">
          <v-pagination v-if="pageCount > 1" v-model="page" :length="pageCount" circle @input="changePage"></v-pagination>
        </v-container>
      </v-col>
    </v-row>

    <AppDialog
      v-model="renameDialog"
      type="action"
      :title="$t('folder.rename')"
      icon="mdi-folder-edit-outline"
      color="primary"
      width="420"
      :confirm-text="$t('folder.save')"
      :confirm-loading="renaming"
      :confirm-disabled="!renameValid"
      @confirm="submitRename(false)"
    >
      <v-text-field
        :value="renameName"
        :label="$t('folder.newName')"
        :counter="maxLen"
        outlined
        autofocus
        hide-details="auto"
        @input="onRenameInput"
        @keydown.enter="renameValid && submitRename(false)"
      ></v-text-field>
    </AppDialog>

    <AppDialog
      v-model="mergeDialog"
      type="confirm"
      :title="$t('folder.mergeTitle')"
      color="deep-orange"
      confirm-dark
      width="420"
      :confirm-text="$t('folder.merge')"
      :confirm-loading="renaming"
      @confirm="submitRename(true)"
    >
      {{ $t('folder.mergeConfirm', { target: mergeTarget, count: mergeCount }) }}
    </AppDialog>
  </div>
</template>

<script>
import BookCards from "~/components/BookCards.vue";
import { cleanSegment } from "~/components/FolderEditor.vue";

export default {
  components: { BookCards },
  data: () => ({
    tree: [],
    books: [],
    total: 0,
    page: 1,
    loaded: false,
    maxLen: 24,
    renameDialog: false,
    renameName: "",
    renaming: false,
    mergeDialog: false,
    mergeTarget: "",
    mergeCount: 0,
  }),
  head() {
    return { title: this.path ? this.path : this.$t("folder.title") };
  },
  computed: {
    path() {
      return this.$route.query.path || "";
    },
    isAdmin() {
      return this.$store.state.user?.is_admin === true;
    },
    pageSize() {
      if (process.client) {
        const stored = localStorage.getItem("defaultPageSize");
        if (stored) {
          return parseInt(stored);
        }
      }
      return this.$store?.state?.default_page_size || 60;
    },
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    segments() {
      return this.path ? this.path.split(".") : [];
    },
    crumbs() {
      return this.segments.map((name, idx) => ({ name, path: this.segments.slice(0, idx + 1).join(".") }));
    },
    subFolders() {
      if (this.segments.length === 0) {
        return this.tree;
      }
      return this.segments.reduce((nodes, name) => nodes.find((n) => n.name === name)?.children || [], this.tree);
    },
    renameValid() {
      return !!this.renameName && this.renameName !== this.segments[this.segments.length - 1];
    },
  },
  watch: {
    "$route.query": "loadBooks",
  },
  created() {
    this.$store.commit("navbar", true);
    this.page = 1 + Math.floor(parseInt(this.$route.query.start || 0) / this.pageSize);
  },
  mounted() {
    this.loadTree();
    this.loadBooks();
  },
  methods: {
    childPath(name) {
      return this.path ? `${this.path}.${name}` : name;
    },
    goTo(path) {
      this.$router.push({ query: path ? { path } : {} });
    },
    changePage() {
      this.$router.push({ query: { ...this.$route.query, start: (this.page - 1) * this.pageSize, size: this.pageSize } });
    },
    async loadTree() {
      const rsp = await this.$backend("/folders");
      this.tree = rsp.err === "ok" ? rsp.folders : [];
    },
    async loadBooks() {
      const query = new URLSearchParams({ path: this.path, start: this.$route.query.start || 0, size: this.pageSize });
      const rsp = await this.$backend(`/folder/books?${query}`);
      if (rsp.err !== "ok") {
        this.$alert("error", rsp.msg);
        return;
      }
      this.books = rsp.books;
      this.total = rsp.total;
      this.page = 1 + Math.floor(parseInt(this.$route.query.start || 0) / this.pageSize);
      this.loaded = true;
    },
    openRename() {
      this.renameName = this.segments[this.segments.length - 1];
      this.renameDialog = true;
    },
    onRenameInput(value) {
      this.renameName = cleanSegment(value);
    },
    async submitRename(merge) {
      this.renaming = true;
      try {
        const rsp = await this.$backend("/folder/rename", {
          method: "POST",
          body: JSON.stringify({ path: this.path, name: this.renameName, merge }),
        });
        if (rsp.err === "folder.exists" && !merge) {
          this.mergeTarget = rsp.target;
          this.mergeCount = rsp.count;
          this.mergeDialog = true;
        } else if (rsp.err === "ok") {
          this.mergeDialog = false;
          this.renameDialog = false;
          this.$alert("success", rsp.msg);
          await this.loadTree();
          this.goTo(rsp.path);
        } else {
          this.$alert("error", rsp.msg);
        }
      } catch (error) {
        this.$alert("error", this.$t("message.networkError"));
      } finally {
        this.renaming = false;
      }
    },
  },
};
</script>
