<template>
  <div id="txt-main">
    <v-navigation-drawer v-model="sidebar" app fixed width="240"
                         class="d-flex flex-column" style="height: 100%"
                         :clipped="$vuetify.breakpoint.lgAndUp">
      <v-subheader style="height: 48px">{{ name }}</v-subheader>
      <v-virtual-scroll
        style="height: calc(100% - 48px)"
        :items="content" bench="20"
        item-height="40">
        <template v-slot:default="{item,index}">
          <v-list-item dense :key="item.title" @click="getNovelContent(index)"
                       :color="selected===index?'primary':''">
            <v-list-item-content>
              <v-list-item-title>
                {{ item.title }}
              </v-list-item-title>
            </v-list-item-content>
          </v-list-item>
        </template>
      </v-virtual-scroll>
    </v-navigation-drawer>

    <v-app-bar class="px-0" color="blue" dense dark app fixed clipped-left extension-height="64">

      <v-toolbar-title class="ml-n5 mr-12 align-center">
        <v-app-bar-nav-icon @click.stop="sidebar = !sidebar">
          <v-icon>menu</v-icon>
        </v-app-bar-nav-icon>
        <span class="cursor-pointer" @click="$router.push('/')">
          {{ name }}
        </span>
      </v-toolbar-title>

    </v-app-bar>
    <div>
      <v-container>
        <v-card outlined v-if="!inited" width="300" style="margin: 0 auto">
          <v-card-title ref="tipTitle">{{ $t('reader.tip.title') }}</v-card-title>
          <v-card-text ref="tip">
            {{ $t('reader.tip.content') }}
          </v-card-text>
        </v-card>
        <div v-else>
          <div class="d-flex justify-center align-content-center" style="margin-bottom: 20px" v-if="loading">
            <v-progress-circular color="primary" indeterminate size="28" style="margin-right: 10px"/>
            {{ $t('reader.loading') }}
          </div>
          <div style="word-wrap: break-word" v-html="novelContent" v-show="!loading"/>
          <div class="d-flex justify-space-between" v-show="novelContent && !loading">
            <v-btn color="info" elevation="0" :disabled="selected===0"
                   @click="getNovelContent(selected-1)">
              {{ $t('reader.previous') }}
            </v-btn>
            <v-btn outlined elevation="0" @click="sidebar=true" v-show="!sidebar">
              {{ $t('reader.directory') }}
            </v-btn>
            <v-btn color="primary" elevation="0" :disabled="selected===content.length-1"
                   @click="getNovelContent(selected+1)">
              {{ $t('reader.next') }}
            </v-btn>
          </div>
        </div>
        <app-footer v-if="$store.state.nav"></app-footer>
      </v-container>
    </div>
  </div>
</template>

<script>
import AppFooter from "~/components/AppFooter.vue"

export default {
  name: "TxtReader",
  components: {AppFooter},
  data: () => ({
    sidebar: null,
    bookid: null,
    items: ["1", "2", "3"],
    content: [],
    inited: false,
    wait: 0,
    name: null,
    novelContent: '',
    selected: -1,
    loading: true,
    tip: {
      title: this.$t('reader.tip.title'),
      content: this.$t('reader.tip.content')
    }
  }),
  created() {
    this.bookid = this.$route.params.bid;
    this.$store.commit("navbar", false);
    this.init()
  },
  methods: {
    init() {
      this.loading = true
      this.$backend(`/book/txt/init?id=${this.bookid}&test=0`)
        .then(rsp => {
          if (rsp.err !== "ok") {
            this.tip.title = this.$t('reader.error');
            this.tip.content = rsp.msg;
            return;
          }
          if (rsp.msg === this.$t('reader.parsed')) {
            this.inited = true;
            this.content = rsp.data.content;
            this.name = rsp.data.name;
            this.getNovelContent(0);
          } else {
            this.wait = parseInt(rsp.data.wait);
            let queLen = parseInt(rsp.data.que);
            this.name = rsp.data.name;
            if (queLen > 0) {
              this.tip.title = this.$t('reader.queue');
              this.tip.content = this.$t('reader.queueMessage', { queLen });
              return;
            }
            let intvl = setInterval(() => {
              this.wait--;
              this.tip.content = this.$t('reader.parsing', { wait: this.wait });
              if (this.wait <= 0) {
                clearInterval(intvl);
                this.tip.content = this.$t('reader.timeoutMessage');
                this.tip.title = this.$t('reader.timeout');
                return;
              }
              if (this.wait % 5 !== 0) return;
              this.$backend(`/book/txt/init?id=${this.bookid}&test=1`,)
                .then(res => {
                  if (res.err === "ok" && res.msg === this.$t('reader.parsed')) {
                    this.inited = true;
                    this.content = res.data.content;
                    this.name = res.data.name;
                    this.getNovelContent(0);
                    clearInterval(intvl);
                  }
                })
            }, 1000)
          }
        }).finally(() => {
        this.loading = false
      });
    },
    getNovelContent(i) {
      if (this.selected === i) return;
      this.selected = i;
      const {title, start, end} = {...this.content[i]};
      this.loading = true;
      console.log(title, start, end);
      this.$backend(`/read/txt?id=${this.bookid}&start=${start}&end=${end}`)
        .then(res => {
          if (res.err !== "ok") {
            this.novelContent = this.$t('reader.contentError', { msg: res.msg });
            return;
          }
          this.novelContent = title + "<br>" + res.content;
        }).finally(() => {
        this.loading = false;
        document.getElementsByTagName('html')[0].style.scrollBehavior = 'smooth';
        document.getElementsByTagName('html')[0].scrollTop = 0;
      })
    }
  }
}
</script>

<style scoped>

</style>
