<template>
  <div class="readme-page">
    <v-card class="readme-card">
      <header class="readme-header">
        <h1>{{ $t('opds.introduction') }}</h1>
        <img class="readme-icon" src="/icons/opds.svg" alt="OPDS Icon" />
      </header>
      <section>
        <h2>{{ $t('opds.link') }}</h2>
        <p>
          {{ $t('opds.linkDescription') }}
          <code>{{ opdsUrl }}</code>
          <v-btn icon :aria-label="$t('common.copy')" @click="copyOpdsUrl($event)" :data-copy-text="opdsUrl" class="copy-btn">
            <v-icon :color="copied ? 'green' : ''">{{ copied ? 'mdi-check' : 'mdi-content-copy' }}</v-icon>
          </v-btn>
        </p>
      </section>
      <section>
        <h2>{{ $t('opds.commonReaders') }}</h2>
        <ul>
          <li><strong>Readest</strong>：{{ $t('opds.readestDescription') }} <a href="https://apps.apple.com/us/app/readest-ebook-reader/id6738622779" target="_blank" rel="noopener noreferrer">[{{ $t('opds.download') }}]</a></li>
          <li><strong>{{ $t('opds.moonReader') }}</strong>：{{ $t('opds.moonReaderDescription') }} <a href="https://play.google.com/store/apps/details?id=com.flyersoft.moonreader" target="_blank" rel="noopener noreferrer">[{{ $t('opds.download') }}]</a></li>
        </ul>
      </section>
      <section>
        <h2>{{ $t('opds.configurationGuide') }}</h2>
        <ol>
          <li>{{ $t('opds.addLibrary') }}</li>
          <li>{{ $t('opds.enterLink') }}</li>
          <li>{{ $t('opds.completeAuth') }}</li>
          <li>{{ $t('opds.startReading') }}</li>
        </ol>

        <h2>{{ $t('opds.note') }}</h2>
        <p>{{ $t('opds.moonReaderNote') }}</p>
        <ol>
          <li>{{ $t('opds.disablePrivateLibrary') }}</li>
          <li>{{ $t('opds.enableGuestAccess') }}</li>
        </ol>
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
    opdsUrl() {
      return process.client ? `${siteBaseUrl(this.$store, { allowCache: false })}/opds/` : ''
    }
  },
  methods: {
    copyOpdsUrl(event) {
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
