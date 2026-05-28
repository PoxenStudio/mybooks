<template>
  <div class="opds-page">
    <h1>{{ $t('opds.introduction') }}</h1>
    <img class="opds-icon" src="/icons/opds.svg" alt="OPDS Icon" />
    <section>
      <h2>{{ $t('opds.link') }}</h2>
      <p>
        {{ $t('opds.linkDescription') }}
        <code>{{ opdsUrl }}</code>
        <v-btn icon @click="copyOpdsUrl">
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
  </div>
</template>

<script>
export default {
  data() {
    return {
      opdsUrl: process.client ? window.location.origin + '/opds/' : '',
      copied: false
    }
  },
  methods: {
    async copyOpdsUrl() {
      try {
        await navigator.clipboard.writeText(this.opdsUrl)
        this.copied = true
        setTimeout(() => {
          this.copied = false
        }, 2000)
      } catch (err) {
        console.error('复制失败:', err)
      }
    }
  }
}
</script>

<style scoped>
.opds-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 20px;
}

h1 {
  text-align: center;
  margin-bottom: 10px;
}

.opds-icon {
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
