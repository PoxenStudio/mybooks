<template>
  <div class="opds-page">
    <h1>{{ $t('opds.introduction') }}</h1>
    <section>
      <h2>{{ $t('opds.link') }}</h2>
      <p>{{ $t('opds.linkDescription') }}<code>{{ opdsUrl }}</code></p>
    </section>
    <section>
      <h2>{{ $t('opds.commonReaders') }}</h2>
      <ul>
        <li><strong>KyBook</strong>：{{ $t('opds.kybookDescription') }} <a href="https://apps.apple.com/app/kybook/id1049898139" target="_blank" rel="noopener noreferrer">[{{ $t('opds.download') }}]</a></li>
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
      opdsUrl: process.client ? window.location.origin + '/opds/' : ''
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
  margin-bottom: 30px;
}

section {
  margin-bottom: 30px;
}

h2 {
  margin-bottom: 15px;
}

ul, ol {
  padding-left: 20px;
}

code {
  background: #f5f5f5;
  padding: 2px 5px;
  border-radius: 3px;
}
</style>
