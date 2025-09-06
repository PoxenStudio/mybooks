<template>
  <div class="audio-player-container">
    <!-- 上方区域 60% -->
    <div class="audio-upper-section">
      <!-- 左侧封面区域 -->
      <div class="cover-section">
        <div class="cover-container">
          <v-img
            :src="book.img"
            :aspect-ratio="3/4"
            class="book-cover"
            contain
          ></v-img>
          <div class="book-info">
            <h2 class="book-title">{{ book.title }}</h2>
            <p class="book-author">{{ book.authors }}</p>
          </div>
        </div>
      </div>

      <!-- 右侧音频列表 -->
      <div class="playlist-section">
        <div class="playlist-header">
          <h3>{{ $t('audio.playlist') }}</h3>
          <v-chip v-if="audioFiles.length > 0" small outlined>
            {{ audioFiles.length }} {{ $t('audio.chapters') }}
          </v-chip>
        </div>

        <div class="playlist-container" v-if="audioFiles.length > 0">
          <div
            v-for="(audio, index) in audioFiles"
            :key="index"
            class="playlist-item"
            :class="{ 'active': currentTrackIndex === index }"
            @click="selectTrack(index)"
          >
            <div class="track-number">{{ index + 1 }}</div>
            <div class="track-info">
              <div class="track-title">{{ getDisplayName(audio.filename) }}</div>
              <div class="track-duration">{{ formatFileSize(audio.size) }}</div>
            </div>
            <v-icon v-if="currentTrackIndex === index && isPlaying" color="primary">
              mdi-volume-high
            </v-icon>
          </div>
        </div>

        <div v-else class="no-audio-message">
          <v-icon large color="grey">mdi-headphones-off</v-icon>
          <p>{{ $t('audio.noAudioFiles') }}</p>
        </div>
      </div>
    </div>

    <!-- 下方播放控制条 40% -->
    <div class="audio-controls-section">
      <!-- 进度条 -->
      <div class="progress-section">
        <div class="time-display">
          <span>{{ formatTime(currentTime) }}</span>
          <span>{{ formatTime(duration) }}</span>
        </div>
        <v-slider
          v-model="progress"
          :max="100"
          hide-details
          @change="seekTo"
          @mousedown="isDragging = true"
          @mouseup="isDragging = false"
          class="progress-slider"
        ></v-slider>
      </div>

      <!-- 控制按钮 -->
      <div class="controls-section">
        <div class="main-controls">
          <!-- 上一首 -->
          <v-btn
            icon
            large
            @click="previousTrack"
            :disabled="currentTrackIndex <= 0"
            class="control-btn"
          >
            <v-icon>mdi-skip-previous</v-icon>
          </v-btn>

          <!-- 播放/暂停 -->
          <v-btn
            icon
            x-large
            @click="togglePlay"
            :disabled="!currentAudio"
            class="play-btn"
          >
            <v-icon>{{ isPlaying ? 'mdi-pause' : 'mdi-play' }}</v-icon>
          </v-btn>

          <!-- 下一首 -->
          <v-btn
            icon
            large
            @click="nextTrack"
            :disabled="currentTrackIndex >= audioFiles.length - 1"
            class="control-btn"
          >
            <v-icon>mdi-skip-next</v-icon>
          </v-btn>
        </div>

        <div class="secondary-controls">
          <!-- 倍速控制 -->
          <v-menu offset-y>
            <template v-slot:activator="{ on, attrs }">
              <v-btn
                text
                v-bind="attrs"
                v-on="on"
                class="speed-btn"
              >
                {{ playbackRate }}x
              </v-btn>
            </template>
            <v-list>
              <v-list-item
                v-for="rate in playbackRates"
                :key="rate"
                @click="setPlaybackRate(rate)"
              >
                <v-list-item-title>{{ rate }}x</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-menu>

          <!-- 定时关闭 -->
          <v-menu offset-y>
            <template v-slot:activator="{ on, attrs }">
              <v-btn
                text
                v-bind="attrs"
                v-on="on"
                class="timer-btn"
                :color="sleepTimer ? 'primary' : ''"
              >
                <v-icon left>mdi-timer</v-icon>
                {{ sleepTimer ? sleepTimer.label : $t('audio.timer') }}
              </v-btn>
            </template>
            <v-list>
              <v-list-item @click="setSleepTimer(null)">
                <v-list-item-title>{{ $t('audio.timerOff') }}</v-list-item-title>
              </v-list-item>
              <v-list-item
                v-for="timer in sleepTimers"
                :key="timer.value"
                @click="setSleepTimer(timer)"
              >
                <v-list-item-title>{{ timer.label }}</v-list-item-title>
              </v-list-item>
            </v-list>
          </v-menu>

          <!-- 音量控制 -->
          <div class="volume-control">
            <v-icon>mdi-volume-high</v-icon>
            <v-slider
              v-model="volume"
              :max="100"
              hide-details
              @input="setVolume"
              class="volume-slider"
            ></v-slider>
          </div>
        </div>
      </div>
    </div>

    <!-- 隐藏的音频元素 -->
    <audio
      ref="audioPlayer"
      @loadedmetadata="onLoadedMetadata"
      @timeupdate="onTimeUpdate"
      @ended="onTrackEnded"
      @play="onPlay"
      @pause="onPause"
      preload="metadata"
    ></audio>
  </div>
</template>

<script>
export default {
  async asyncData({ params, app }) {
    const bookId = params.id;

    try {
      // 获取书籍信息
      const bookResponse = await app.$backend(`/book/${bookId}`);
      if (bookResponse.err !== 'ok') {
        throw new Error(bookResponse.msg || '书籍不存在');
      }

      // 获取音频文件列表
      const audioResponse = await app.$backend(`/api/audio/${bookId}`);

      return {
        book: bookResponse.book,
        audioFiles: audioResponse.audios || [],
        audioStatus: audioResponse.status || 'unavailable'
      };
    } catch (error) {
      console.error('Error loading audio data:', error);
      return {
        book: {},
        audioFiles: [],
        audioStatus: 'unavailable'
      };
    }
  },

  head() {
    return {
      title: `${this.book.title || ''} - ${this.$t('audio.audioBook')}`,
      bodyAttrs: {
        class: 'audio-player-page'
      }
    };
  },

  data() {
    return {
      // 播放状态
      isPlaying: false,
      currentTrackIndex: 0,
      currentTime: 0,
      duration: 0,
      progress: 0,
      isDragging: false,

      // 音频设置
      playbackRate: 1,
      playbackRates: [0.5, 1, 1.25, 1.5, 2],
      volume: 80,

      // 定时器
      sleepTimer: null,
      sleepTimerInterval: null,
      sleepTimers: [
        { value: 'current', label: this.$t('audio.currentChapter') },
        { value: 15, label: this.$t('audio.timer15min') },
        { value: 30, label: this.$t('audio.timer30min') },
        { value: 60, label: this.$t('audio.timer1hour') }
      ]
    };
  },

  computed: {
    currentAudio() {
      return this.audioFiles[this.currentTrackIndex];
    }
  },

  mounted() {
    this.initializePlayer();
  },

  beforeDestroy() {
    this.clearSleepTimer();
    if (this.$refs.audioPlayer) {
      this.$refs.audioPlayer.pause();
    }
  },

  methods: {
    initializePlayer() {
      if (this.audioFiles.length > 0) {
        this.loadTrack(0);
      }
      this.setVolume(this.volume);
    },

    loadTrack(index) {
      if (index >= 0 && index < this.audioFiles.length) {
        this.currentTrackIndex = index;
        const audio = this.audioFiles[index];
        this.$refs.audioPlayer.src = audio.url;
        this.$refs.audioPlayer.load();
      }
    },

    selectTrack(index) {
      if (index !== this.currentTrackIndex) {
        this.loadTrack(index);
        if (this.isPlaying) {
          this.$nextTick(() => {
            this.$refs.audioPlayer.play();
          });
        }
      }
    },

    togglePlay() {
      if (!this.$refs.audioPlayer) return;

      if (this.isPlaying) {
        this.$refs.audioPlayer.pause();
      } else {
        this.$refs.audioPlayer.play();
      }
    },

    previousTrack() {
      if (this.currentTrackIndex > 0) {
        this.loadTrack(this.currentTrackIndex - 1);
        if (this.isPlaying) {
          this.$nextTick(() => {
            this.$refs.audioPlayer.play();
          });
        }
      }
    },

    nextTrack() {
      if (this.currentTrackIndex < this.audioFiles.length - 1) {
        this.loadTrack(this.currentTrackIndex + 1);
        if (this.isPlaying) {
          this.$nextTick(() => {
            this.$refs.audioPlayer.play();
          });
        }
      }
    },

    seekTo(value) {
      if (this.$refs.audioPlayer && this.duration > 0) {
        const seekTime = (value / 100) * this.duration;
        this.$refs.audioPlayer.currentTime = seekTime;
      }
    },

    setPlaybackRate(rate) {
      this.playbackRate = rate;
      if (this.$refs.audioPlayer) {
        this.$refs.audioPlayer.playbackRate = rate;
      }
    },

    setVolume(value) {
      this.volume = value;
      if (this.$refs.audioPlayer) {
        this.$refs.audioPlayer.volume = value / 100;
      }
    },

    setSleepTimer(timer) {
      this.clearSleepTimer();
      this.sleepTimer = timer;

      if (timer) {
        if (timer.value === 'current') {
          // 当前章节结束后停止
          this.sleepTimer.type = 'current';
        } else {
          // 定时停止
          this.sleepTimer.type = 'timeout';
          this.sleepTimer.endTime = Date.now() + (timer.value * 60 * 1000);
          this.sleepTimerInterval = setInterval(() => {
            if (Date.now() >= this.sleepTimer.endTime) {
              this.pauseAndClearTimer();
            }
          }, 1000);
        }
      }
    },

    clearSleepTimer() {
      if (this.sleepTimerInterval) {
        clearInterval(this.sleepTimerInterval);
        this.sleepTimerInterval = null;
      }
      this.sleepTimer = null;
    },

    pauseAndClearTimer() {
      this.$refs.audioPlayer.pause();
      this.clearSleepTimer();
    },

    // 音频事件处理
    onLoadedMetadata() {
      this.duration = this.$refs.audioPlayer.duration;
      this.$refs.audioPlayer.playbackRate = this.playbackRate;
    },

    onTimeUpdate() {
      if (!this.isDragging) {
        this.currentTime = this.$refs.audioPlayer.currentTime;
        if (this.duration > 0) {
          this.progress = (this.currentTime / this.duration) * 100;
        }
      }
    },

    onTrackEnded() {
      // 检查定时器
      if (this.sleepTimer && this.sleepTimer.type === 'current') {
        this.pauseAndClearTimer();
        return;
      }

      // 自动播放下一首
      if (this.currentTrackIndex < this.audioFiles.length - 1) {
        this.nextTrack();
      } else {
        this.isPlaying = false;
      }
    },

    onPlay() {
      this.isPlaying = true;
    },

    onPause() {
      this.isPlaying = false;
    },

    // 工具方法
    getDisplayName(filename) {
      // 移除前缀（4个数字加下划线）
      return filename.replace(/^\d{4}_/, '');
    },

    formatTime(seconds) {
      if (!seconds || isNaN(seconds)) return '00:00';
      const mins = Math.floor(seconds / 60);
      const secs = Math.floor(seconds % 60);
      return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
    },

    formatFileSize(bytes) {
      if (!bytes) return '';
      const mb = bytes / (1024 * 1024);
      return `${mb.toFixed(1)}MB`;
    }
  }
};
</script>

<style scoped>
.audio-player-container {
  height: 100vh;
  background: linear-gradient(135deg, #2c2c2c 0%, #1a1a1a 100%);
  color: #ffffff;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.audio-upper-section {
  height: 60%;
  display: flex;
  padding: 20px;
  gap: 20px;
}

.cover-section {
  flex: 0 0 35%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.cover-container {
  max-width: 300px;
  width: 100%;
  text-align: center;
}

.book-cover {
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  margin-bottom: 20px;
}

.book-title {
  font-size: 1.5rem;
  font-weight: bold;
  margin-bottom: 8px;
  color: #ffffff;
}

.book-author {
  font-size: 1rem;
  color: #cccccc;
  margin: 0;
}

.playlist-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.playlist-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #404040;
}

.playlist-header h3 {
  margin: 0;
  color: #ffffff;
}

.playlist-container {
  flex: 1;
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: #555555 #2c2c2c;
}

.playlist-container::-webkit-scrollbar {
  width: 6px;
}

.playlist-container::-webkit-scrollbar-track {
  background: #2c2c2c;
}

.playlist-container::-webkit-scrollbar-thumb {
  background: #555555;
  border-radius: 3px;
}

.playlist-item {
  display: flex;
  align-items: center;
  padding: 12px;
  cursor: pointer;
  border-radius: 8px;
  margin-bottom: 4px;
  transition: all 0.2s;
}

.playlist-item:hover {
  background-color: #404040;
}

.playlist-item.active {
  background-color: #9C27B0;
}

.track-number {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background-color: #555555;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  margin-right: 12px;
  flex-shrink: 0;
}

.playlist-item.active .track-number {
  background-color: rgba(255, 255, 255, 0.2);
}

.track-info {
  flex: 1;
  min-width: 0;
}

.track-title {
  font-weight: 500;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.track-duration {
  font-size: 0.875rem;
  color: #cccccc;
}

.no-audio-message {
  text-align: center;
  padding: 40px 20px;
  color: #888888;
}

.audio-controls-section {
  height: 40%;
  background: #1a1a1a;
  border-top: 1px solid #404040;
  padding: 20px;
  display: flex;
  flex-direction: column;
}

.progress-section {
  margin-bottom: 20px;
}

.time-display {
  display: flex;
  justify-content: space-between;
  font-size: 0.875rem;
  color: #cccccc;
  margin-bottom: 8px;
}

.progress-slider {
  margin: 0;
}

.controls-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 20px;
}

.main-controls {
  display: flex;
  align-items: center;
  gap: 20px;
}

.control-btn {
  background-color: #404040 !important;
}

.play-btn {
  background-color: #9C27B0 !important;
  color: white !important;
}

.secondary-controls {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
  justify-content: center;
}

.speed-btn,
.timer-btn {
  background-color: #404040 !important;
  color: white !important;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 120px;
}

.volume-slider {
  margin: 0;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .audio-upper-section {
    flex-direction: column;
    height: 50%;
  }

  .cover-section {
    flex: 0 0 auto;
  }

  .cover-container {
    max-width: 200px;
  }

  .playlist-section {
    flex: 1;
    min-height: 200px;
  }

  .audio-controls-section {
    height: 50%;
  }

  .secondary-controls {
    flex-direction: column;
    gap: 10px;
  }

  .main-controls {
    gap: 10px;
  }
}

/* 全局样式覆盖 */
:global(body.audio-player-page) {
  background: #1a1a1a !important;
}

:global(.audio-player-page .v-application) {
  background: #1a1a1a !important;
}

:global(.audio-player-page .v-navigation-drawer),
:global(.audio-player-page .v-app-bar) {
  display: none !important;
}

:global(.audio-player-page .v-main) {
  padding: 0 !important;
}
</style>
