<template>
  <div class="webdav-page">
    <h1>{{ $t('webdav.introduction') }}</h1>
    <img class="webdav-icon" src="/icons/webdav.svg" alt="WebDAV Icon" />
    <section>
      <h2>{{ $t('webdav.link') }}</h2>
      <p>
        {{ $t('webdav.linkDescription') }}
        <code>{{ webdavUrl }}</code>
        <v-btn icon @click="copyWebdavUrl($event)" :data-copy-text="webdavUrl" class="copy-btn">
          <v-icon :color="copied ? 'green' : ''">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
        </v-btn>
      </p>
    </section>
    <section>
      <h2>客户端访问</h2>
      <p>可以在任何支持WebDAV访问的阅读器、应用程序或者电子书上直接访问书库内容，如Koodo Reader，以及文石、汉王等设备。</p>
      <br />
      <p>参考文章：<a href="https://mp.weixin.qq.com/s/82zFUwv46CLFzHnIf57IyQ" target="_blank" rel="noopener noreferrer">支持以WebDAV直接访问书库</a><br />
        不支持匿名访问，需要输入书库中的用户名和密码。
      </p>
      <br />
      <p>如果启用了WebDAV同步功能，支持WebDAV同步数据的阅读器，如Koodo Reader, 可以在reader目录下进行读写操作，实现同步功能。</p>
    </section>
  </div>
</template>

<script>
export default {
  data() {
    return {
      webdavUrl: process.client ? window.location.origin + '/books/' : '',
      copied: false
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
.webdav-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
}

h1 {
  text-align: center;
  margin-bottom: 10px;
}

.webdav-icon {
  display: block;
  margin: 0 auto 24px;
  width: 72px;
}

section {
  margin-bottom: 30px;
}

h2 {
  margin-bottom: 15px;
}

ul,
ol {
  padding-left: 20px;
}

code {
  background: #f5f5f5;
  padding: 2px 5px;
  border-radius: 3px;
  margin-right: 8px;
}
</style>
