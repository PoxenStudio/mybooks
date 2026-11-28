<template>
  <div class="readme-page">
    <v-card class="readme-card">
      <header class="readme-header">
        <h1>{{ $t('webdav.introduction') }}</h1>
        <img class="readme-icon" src="/icons/webdav.svg" alt="WebDAV Icon" />
      </header>
      <section>
        <h2>{{ $t('webdav.link') }}</h2>
        <p>
          {{ $t('webdav.linkDescription') }}
          <code>{{ webdavUrl }}</code>
          <v-btn icon :aria-label="$t('common.copy')" @click="copyWebdavUrl($event)" :data-copy-text="webdavUrl" class="copy-btn">
            <v-icon :color="copied ? 'green' : ''">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
          </v-btn>
        </p>
      </section>
      <section>
        <h2>客户端访问</h2>
        <p>可以在任何支持WebDAV访问的阅读器、应用程序或者电子书上直接访问书库内容，如Koodo Reader，以及文石、汉王等设备。</p>
        <p>参考文章：<a href="https://mp.weixin.qq.com/s/82zFUwv46CLFzHnIf57IyQ" target="_blank" rel="noopener noreferrer">支持以WebDAV直接访问书库</a></p>
        <p>不支持匿名访问，需要输入书库中的用户名和密码。</p>
        <p>如果启用了WebDAV同步功能，支持WebDAV同步数据的阅读器，如Koodo Reader, 可以在reader目录下进行读写操作，实现同步功能。</p>
      </section>
    </v-card>
  </div>
</template>

<script>
import { siteBaseUrl } from '~/utils/siteUrl'

export default {
  data() {
    return {
      copied: false
    }
  },
  computed: {
    webdavUrl() {
      return process.client ? `${siteBaseUrl(this.$store, { allowCache: false })}/books/` : ''
    }
  },
  methods: {
    copyWebdavUrl(event) {
      const btn = event.target.closest('.copy-btn')
      if (!btn) return
      const text = btn.getAttribute('data-copy-text') || ''
      if (!text) return

      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      try {
        document.execCommand('copy')
        this.copied = true
        setTimeout(() => {
          this.copied = false
        }, 2000)
      } catch (e) {
        console.error('复制失败:', e)
      }
      document.body.removeChild(ta)
    }
  }
}
</script>

<style scoped>
.readme-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 20px 40px;
}

.readme-page .readme-card {
  padding: 32px;
  border-radius: 12px !important;
}

.readme-header {
  text-align: center;
  margin-bottom: 28px;
}

h1 {
  margin: 0 0 16px;
  font-size: 1.5rem;
}

.readme-icon {
  display: block;
  width: 72px;
  margin: 0 auto;
}

section {
  margin-bottom: 28px;
}

section:last-child {
  margin-bottom: 0;
}

h2 {
  margin: 0 0 12px;
  font-size: 1.125rem;
}

p {
  margin: 0 0 8px;
  line-height: 1.7;
}

ul,
ol {
  padding-left: 20px;
  line-height: 1.7;
}

li {
  margin-bottom: 6px;
}

code {
  padding: 2px 6px;
  margin-right: 8px;
  border-radius: var(--ds-radius-xs);
  background: var(--ds-surface-strong);
  color: var(--ds-body);
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.875em;
  word-break: break-all;
}

@media (max-width: 600px) {
  .readme-card {
    padding: 20px;
  }
}
</style>
