<template>
  <div>
    <v-row align="start">
        <v-col cols="12">
            <v-dialog v-model="dialog_epub2audio" persistent width="380">
                <v-card class="dialog-border">
                    <v-card-title class="">{{ $t('book.convertToAudio') }}</v-card-title>
                    <v-card-text v-if="audios.status === AUDIO_STATUS.FAILED">
                        <p style="color: red; font-weight: bold;">{{ $t('book.conversionFailed') }} <br/>
                            {{ audios.progress && audios.progress.error_message ? audios.progress.error_message : $t('book.defaultFailedReason') }}
                        </p>
                    </v-card-text>
                    <v-card-text>
                        <p>{{ $t('book.convertToAudioNote') }}</p>
                        <v-select
                            :items="voice_options"
                            outlined
                            dense
                            v-model="voice_name"
                            :label="$t('book.chooseVoice')"
                            item-text="display_name"
                            item-value="voice_name"
                            required
                        >
                            <template v-slot:selection="{ item }">
                                {{ item.display_name }}
                            </template>
                            <template v-slot:item="{ item }">
                                <v-list-item-content>
                                    <v-list-item-title style="font-size: 15px;">{{ item.display_name }}</v-list-item-title>
                                </v-list-item-content>
                                <v-list-item-action>
                                    <v-btn
                                        icon
                                        small
                                        @click.stop="play_sample_voice(item)"
                                        :loading="playing_sample === item.voice_name"
                                    >
                                        <v-icon>play_arrow</v-icon>
                                    </v-btn>
                                </v-list-item-action>
                            </template>
                        </v-select>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn color="" text @click="dialog_epub2audio = false">{{ $t('common.cancel') }}</v-btn>
                        <v-spacer></v-spacer>
                        <v-btn color="primary" text @click="generate_audio">{{ $t('common.start') }}</v-btn>
                    </v-card-actions>
                </v-card>
            </v-dialog>

            <v-dialog v-model="dialog_audiolist" persistent width="480">
                <v-card class="dialog-border">
                    <p> </p>
                    <v-card-title class="">
                        {{ $t('book.audioList') }}
                        <span v-if="audios.status === AUDIO_STATUS.PROCESSING && audios.progress && audios.progress.converted_chapters !== undefined"
                              class="ml-2 text-caption">
                            ({{ audios.progress.converted_chapters }}/{{ audios.progress.total_chapters }})
                        </span>
                    </v-card-title>
                    <v-card-text v-if="audios.status === AUDIO_STATUS.PROCESSING">
                        <p style="color: orange; font-weight: bold;">{{ $t('book.conversionInProgress') }}</p>
                        <v-progress-linear
                            v-if="audios.progress && audios.progress.total_chapters > 0"
                            :value="(audios.progress.converted_chapters / audios.progress.total_chapters) * 100"
                            color="primary"
                            height="6"
                        ></v-progress-linear>
                    </v-card-text>
                    <v-card-text v-if="audios.status === AUDIO_STATUS.FAILED">
                        <p style="color: red; font-weight: bold;">{{ $t('book.conversionFailed') }}</p>
                        <p style="color: red; font-weight: bold;">
                            {{ audios.progress && audios.progress.error_message ? audios.progress.error_message : $t('book.defaultFailedReason') }}
                        </p>
                    </v-card-text>
                    <v-card-text>
                        <p>{{ $t('book.convertToAudioNote') }}</p>
                        <div class="audio-scroll-container" style="max-height: 200px; overflow-y: auto; overflow-x: hidden; padding: 12px 12px 0 12px;">
                            <v-row v-for="(audio_item, idx) in this.audios.audios" :key="'audio-' + idx" class="mb-2">
                                <v-col class='py-0'>
                                    <v-btn
                                        icon
                                        small
                                        @click="play_audio_file(audio_item, idx)"
                                        :loading="playing_audio_index === idx && audio_loading"
                                        :color="playing_audio_index === idx ? 'primary' : 'default'"
                                    >
                                        <v-icon>{{ playing_audio_index === idx && !audio_paused ? 'pause' : 'play_arrow' }}</v-icon>
                                    </v-btn>
                                    <span class="ml-2">{{ audio_item.filename }}</span>
                                </v-col>
                            </v-row>
                        </div>
                    </v-card-text>
                    <v-card-actions>
                        <v-btn
                            v-if="audios.status === AUDIO_STATUS.PROCESSING"
                            color="warning"
                            text
                            @click="clear_conversion"
                        >
                            {{ $t('book.cancelConversion') }}
                        </v-btn>
                        <v-btn
                            v-else-if="audios.status === AUDIO_STATUS.CONVERTED"
                            color="error"
                            text
                            @click="clear_conversion"
                        >
                            {{ $t('common.clear') }}
                        </v-btn>
                        <v-spacer></v-spacer>
                        <v-btn color="" text @click="dialog_audiolist = false">{{ $t('common.close') }}</v-btn>
                    </v-card-actions>
                </v-card>
            </v-dialog>

            <v-dialog v-model="dialog_download" persistent width="300">
                <v-card>
                    <v-card-title color="primary" class="">{{ $t('book.downloadBook') }}</v-card-title>
                    <v-card-text>
                        <v-list v-if="book.files.length > 0">
                            <v-list-item :key="'file-'+file.format" v-for="file in book.files" target="_blank"
                                         :href="file.href">
                                <v-list-item-avatar color='primary'>
                                    <v-icon dark>get_app</v-icon>
                                </v-list-item-avatar>
                                <v-list-item-content>
                                    <v-list-item-title>{{ file.format }}</v-list-item-title>
                                    <v-list-item-subtitle v-if="file.size>=1048576">{{
                                            parseInt(file.size / 1048576)
                                        }}MB
                                    </v-list-item-subtitle>
                                    <v-list-item-subtitle v-else>{{
                                            parseInt(file.size / 1024)
                                        }}KB
                                    </v-list-item-subtitle>
                                </v-list-item-content>
                            </v-list-item>
                        </v-list>
                        <p v-else><br/>{{ $t('book.noDownloadableFiles') }}</p>
                    </v-card-text>
                    <v-card-actions>
                        <v-spacer></v-spacer>
                        <v-btn text @click="dialog_download = false">{{ $t('common.close') }}</v-btn>
                        <v-spacer></v-spacer>
                    </v-card-actions>
                </v-card>
            </v-dialog>

            <v-card v-if="dialog_refer">
                <v-toolbar flat dense dark color="primary">
                    {{ $t('book.syncBookInfo') }}
                    <v-spacer></v-spacer>
                    <v-btn outlined text @click="dialog_refer = false">{{ $t('common.cancel') }}</v-btn>
                </v-toolbar>
                <v-card-text xclass="pt-3 px-3 px-sm-6">
                    <p class="py-6 text-center" v-if="refer_books_loading">
                        <v-progress-circular indeterminate color="primary"></v-progress-circular>
                    </p>
                    <p class="py-6 text-center" v-else-if="refer_books.length === 0">{{ $t('book.noMatchingInfo') }}</p>
                    <template v-else>
                        <p>{{ $t('book.selectMatchingRecord') }}</p>
                        <book-cards :books="refer_books">
                            <template #actions="{ book }">
                                <v-card-actions>
                                    <v-chip class="mr-1" small v-if="book.author_sort">{{ book.author_sort }}</v-chip>
                                    <v-chip class="mr-1" small v-if="book.publisher">{{ book.publisher }}</v-chip>
                                    <v-chip small v-if="book.pubyear">{{ book.pubyear }}</v-chip>
                                </v-card-actions>
                                <v-divider></v-divider>
                                <v-card-actions>
                                    <v-chip
                                        small
                                        dark
                                        :href="book.website"
                                        target="__blank"
                                        :color="book.source === '豆瓣' ? 'green' : 'blue'"
                                    >{{ book.source }}
                                    </v-chip
                                    >
                                    <v-spacer></v-spacer>
                                    <v-menu offset-y right>
                                        <template v-slot:activator="{ on }">
                                            <v-btn color="primary" small rounded v-on="on"
                                                   :loading="refer_books_setting_btn_loading">
                                                <v-icon small>done</v-icon>
                                                {{ $t('common.set') }}
                                            </v-btn>
                                        </template>
                                        <v-list dense>
                                            <v-list-item @click="set_refer(book.provider_key, book.provider_value)">
                                                <v-list-item-title>{{ $t('book.setBookInfoAndImage') }}</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item
                                                @click="set_refer(book.provider_key, book.provider_value, { only_meta: 'yes' })">
                                                <v-list-item-title>{{ $t('book.setBookInfoOnly') }}</v-list-item-title>
                                            </v-list-item>
                                            <v-list-item
                                                @click="set_refer(book.provider_key, book.provider_value, { only_cover: 'yes' })">
                                                <v-list-item-title>{{ $t('book.setBookImageOnly') }}</v-list-item-title>
                                            </v-list-item>
                                        </v-list>
                                    </v-menu>
                                </v-card-actions>
                            </template>
                        </book-cards>
                    </template>
                </v-card-text>
            </v-card>

            <v-card v-if="!dialog_refer">
                <v-toolbar flat dense>
                    <!-- download -->
                    <v-btn icon small fab @click="dialog_download = true">
                        <v-icon>get_app</v-icon>
                    </v-btn>
                    <v-btn class="d-none" icon small fab>
                        <v-icon>thumb_up</v-icon>
                    </v-btn>
                    <v-btn class="d-none" icon small fab>
                        <v-icon>share</v-icon>
                    </v-btn>

                    <v-spacer></v-spacer>
                    <v-btn
                        :small="tiny"
                        dark
                        color="primary"
                        class="mx-2 d-flex d-sm-flex"
                        @click="handleReadingStateChange"
                        :loading="readingStateLoading"
                    >
                        {{ readingStateButtonText }}
                    </v-btn>
                    <v-btn
                        :small="tiny"
                        dark
                        color="primary"
                        class="mx-2 d-flex d-sm-flex"
                        @click="switch_to_audio_player"
                        v-if="book.book_type != this.BOOK_TYPE.PHYSICAL"
                    >
                        <v-icon dark>{{ audios.status === AUDIO_STATUS.FAILED ? 'error' : 'audiotrack' }}</v-icon>
                        {{ $t('book.convertToAudio') }}
                        <span v-if="audios.status === AUDIO_STATUS.PROCESSING && audios.progress && audios.progress.converted_chapters !== undefined"
                              class="ml-1">
                            ({{ audios.progress.converted_chapters }}/{{ audios.progress.total_chapters }})
                        </span>
                        <span v-if="audios.status === AUDIO_STATUS.CONVERTED && audios.count > 0"
                              class="ml-1">
                            ({{ audios.count }})
                        </span>
                    </v-btn>
                    <v-btn :small="tiny" dark color="primary" class="mx-2 d-flex d-sm-flex" :href="'/read/' + book.id"
                           target="_blank">
                        <v-icon left v-if="!tiny">import_contacts</v-icon>
                        {{ $t('book.read') }}
                    </v-btn>
                    <template v-if="book.is_owner">
                        <v-menu offset-y>
                            <template v-slot:activator="{ on }">
                                <v-btn v-on="on" dark color="primary" class="ml-2" :small="tiny"
                                >{{ $t('book.manage') }}
                                    <v-icon small>more_vert</v-icon>
                                </v-btn>
                            </template>
                            <v-list>
                                <v-list-item :to="'/book/' + book.id + '/edit'">
                                    <v-icon>settings_applications</v-icon>
                                    {{ $t('book.editBookInfo') }}
                                </v-list-item>
                                <v-list-item @click="get_refer">
                                    <v-icon>apps</v-icon>
                                    {{ $t('book.updateInfoFromInternet') }}
                                </v-list-item>
                                <v-list-item @click="reset_refer">
                                    <v-icon>apps</v-icon>
                                    {{ $t('book.resetInfo') }}
                                </v-list-item>
                                <v-list-item @click="dialog_set_cover = true">
                                    <v-icon>photo</v-icon>
                                    {{ $t('book.setCover') }}
                                </v-list-item>
                                <v-list-item @click="convert_book">
                                    <v-icon>mdi-swap-horizontal</v-icon>
                                    {{ $t('book.convert') }}
                                </v-list-item>
                                <v-divider></v-divider>
                                <v-list-item @click="set_sole">
                                    <v-icon>{{ book.sole ? 'public_off' : 'public' }}</v-icon>
                                    {{ book.sole ? $t('book.setPublic') : $t('book.setSole') }}
                                </v-list-item>
                                <v-list-item @click="delete_book">
                                    <v-icon>delete_forever</v-icon>
                                    {{ $t('book.deleteBook') }}
                                </v-list-item>
                            </v-list>
                        </v-menu>
                    </template>
                </v-toolbar>
                <v-row>
                    <v-col class="mx-auto" cols="8" sm="4">
                        <div style="position: relative; display: inline-block; width: 100%;">
                            <v-img class="book-img" :src="book.img" :aspect-ratio="11 / 15" max-height="500px"
                                   contain style="border-radius: 14px;"></v-img>
                            <!-- 读完状态水印 -->
                            <div
                                v-if="book.state && book.state.read_state === this.READING_STATE.FINISHED"
                                style="
                                    position: absolute;
                                    top: 95%;
                                    left: 0;
                                    right: 0;
                                    height: 40px;
                                    background: rgba(158, 158, 158, 0.7);
                                    display: flex;
                                    align-items: center;
                                    justify-content: center;
                                    z-index: 2;
                                    box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                                    backdrop-filter: blur(2px);
                                "
                            >
                                <span
                                    style="
                                        color: white;
                                        font-size: 1.2rem;
                                        font-weight: bold;
                                        text-shadow: 1px 1px 3px rgba(0,0,0,0.7);
                                        line-height: 1;
                                        letter-spacing: 2px;
                                    "
                                >
                                    {{ $t('readingState.finished') }}
                                </span>
                            </div>
                        </div>
                    </v-col>
                    <v-col cols="12" sm="8">
                        <v-card-text>
                            <div>
                                <p class='title mb-0'>
                                    {{ book.title }}
                                    <v-tooltip bottom>
                                        <template v-slot:activator="{ on, attrs }">
                                            <v-btn
                                                icon
                                                small
                                                class="ml-2"
                                                @click="toggleFavorite"
                                                :loading="favoriteLoading"
                                                :color="isFavorite ? 'red' : 'grey'"
                                                v-bind="attrs"
                                                v-on="on"
                                            >
                                                <v-icon>
                                                    {{ isFavorite ? 'mdi-heart' : 'mdi-heart-outline' }}
                                                </v-icon>
                                            </v-btn>
                                        </template>
                                        <span>{{ $t('readingState.favoriteHint') }}</span>
                                    </v-tooltip>
                                    <v-tooltip bottom>
                                        <template v-slot:activator="{ on, attrs }">
                                            <v-btn
                                                icon
                                                small
                                                class="ml-1"
                                                @click="toggleWants"
                                                :loading="wantsLoading"
                                                :color="isWants ? 'orange' : 'grey'"
                                                v-bind="attrs"
                                                v-on="on"
                                            >
                                                <v-icon>
                                                    {{ isWants ? 'mdi-bookmark-plus' : 'mdi-bookmark-plus-outline' }}
                                                </v-icon>
                                            </v-btn>
                                        </template>
                                        <span>{{ $t('readingState.wantsHint') }}</span>
                                    </v-tooltip>
                                </p>
                                <span color="grey--text">
                                    <v-icon :color="book.sole ? 'red' : 'green'" class="mr-2">
                                        {{ book.sole ? 'public_off' : 'public' }}
                                    </v-icon>
                                    {{ book.author }}{{ $t('book.author') }}，{{ pub_year }}{{ $t('book.year') }}
                                </span>
                                <br />
                                <span v-if="book.book_type==this.BOOK_TYPE.PHYSICAL">
                                    <v-chip rounded small dark color="indigo">
                                        <v-icon>mdi-bookshelf</v-icon>{{ $t('book.bookPhysical') }}
                                    </v-chip>
                                </span>
                                <span v-if="book.book_type==this.BOOK_TYPE.PHYSICAL">{{ $t('book.bookCount')}}: {{book.book_count}}</span>
                                <span
                                    v-if='book.files.length>0 && book.files[0].size >= 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;&nbsp;&nbsp;[{{book.files[0].format}} - {{
                                        parseInt(book.files[0].size / 1048576)
                                    }}MB]
                                </span>
                                <span
                                    v-else-if='book.files.length>0 && book.files[0].size < 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;&nbsp;&nbsp;[{{book.files[0].format}} - {{
                                        parseInt(book.files[0].size / 1024)
                                    }}KB]
                                </span>
                                <span
                                    v-if='book.files.length>1 && book.files[1].size >= 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;[{{book.files[1].format}} - {{
                                        parseInt(book.files[1].size / 1048576)
                                    }}MB]
                                </span>
                                <span
                                    v-else-if='book.files.length>1 && book.files[1].size < 1048576'
                                    color="grey--text" style="font-weight: bold">&nbsp;[{{book.files[1].format}} - {{
                                        parseInt(book.files[1].size / 1024)
                                    }}KB]
                                </span>
                            </div>
                            <v-rating v-model="book.rating" color="yellow accent-4" length="10" readonly dense
                                      small></v-rating>
                            <!-- Reading state display -->
                            <div v-if="book.state && book.state.read_state === this.READING_STATE.READING" class="mt-2">
                                <v-chip
                                    small
                                    color="green"
                                    text-color="white"
                                >
                                    <v-icon small left>mdi-book-open</v-icon>
                                    {{ readingDaysText }}
                                </v-chip>
                            </div>
                            <div v-else-if="book.state && book.state.read_state === this.READING_STATE.FINISHED" class="mt-2">
                                <v-chip
                                    small
                                    color="grey"
                                    text-color="white"
                                >
                                    <v-icon small left>mdi-check</v-icon>
                                    {{ completedReadingText }}
                                </v-chip>
                            </div>
                            <br/>
                            <div class="tag-chips">
                                    <template v-for="author in book.authors" :key="'author-' + author">
                                        <v-chip
                                            rounded
                                            small
                                            dark
                                            color="indigo"
                                            :to="'/author/' + encodeURIComponent(author)"
                                        >
                                        <v-icon>face</v-icon>
                                        {{ author }}
                                    </v-chip>
                                </template>
                                <v-chip rounded small dark color="indigo"
                                        :to="'/publisher/' + encodeURIComponent(book.publisher)">
                                    <v-icon>group</v-icon>
                                    {{ $t('book.publisher') }}：{{ book.publisher }}
                                </v-chip>
                                <v-chip
                                    rounded
                                    small
                                    dark
                                    color="indigo"
                                    v-if="book.series"
                                    :to="'/series/' + encodeURIComponent(book.series)"
                                >
                                    <v-icon>explore</v-icon>
                                    {{ $t('book.series') }}: {{ book.series }}
                                </v-chip>
                                <v-chip rounded small dark color="grey" v-if="book.isbn">
                                    <v-icon>explore</v-icon>
                                    ISBN：{{ book.isbn }}
                                </v-chip>
                                    <template v-for="tag in book.tags" :key="'tag-' + tag">
                                        <v-chip
                                            rounded
                                            small
                                            dark
                                            color="grey"
                                            v-if="tag"
                                            :to="'/tag/' + encodeURIComponent(tag)"
                                        >
                                        <v-icon>loyalty</v-icon>
                                        {{ tag }}
                                    </v-chip>
                                </template>
                            </div>
                        </v-card-text>
                        <v-card-text>
                            <p v-if="book.comments" v-html="book.comments"></p>
                            <p v-else>{{ $t('book.clickToViewDetails') }}</p>
                        </v-card-text>
                    </v-col>
                </v-row>
                <v-card-text class="align-right book-footer">
                    <span class="grey--text"> {{ book.collector }} @ {{ book.timestamp }} </span>
                </v-card-text>
            </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item :href="'/read/' + book.id" target="_blank">
                        <v-list-item-avatar large color="primary">
                            <v-icon dark>import_contacts</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{ $t('book.onlineReading') }}</v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
        <v-col cols="12" sm="5" md="3" v-show="is_txt">
          <v-card outlined>
            <v-list>
              <v-list-item :href="'/book/' + book.id+'/readtxt'" target="_blank">
                <v-list-item-avatar large color="primary">
                  <v-icon dark>import_contacts</v-icon>
                </v-list-item-avatar>
                <v-list-item-content>
                  <v-list-item-title>{{ $t('book.txtOnlineReading', { status: txt_parse_inited ? $t('book.parsed') : $t('book.notParsed') }) }}</v-list-item-title>
                </v-list-item-content>
                <v-list-item-action>
                  <v-icon>mdi-arrow-right</v-icon>
                </v-list-item-action>
              </v-list-item>
            </v-list>
          </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item @click="dialog_download = !dialog_download">
                        <v-list-item-avatar large color="primary">
                            <v-icon dark>get_app</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title>{{ $t('book.download') }}</v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
        <v-col cols="12" :sm="is_txt?6:5" :md="is_txt?3:4">
            <v-card outlined>
                <v-list>
                    <v-list-item @click="switch_audio_dialog" :disabled="book.book_type == this.BOOK_TYPE.PHYSICAL">
                        <v-list-item-avatar large :color="book.book_type == this.BOOK_TYPE.PHYSICAL ? 'grey' : (audios.status === AUDIO_STATUS.FAILED ? 'red' : 'primary')">
                            <v-icon dark>{{ audios.status === AUDIO_STATUS.FAILED ? 'error' : 'audiotrack' }}</v-icon>
                        </v-list-item-avatar>
                        <v-list-item-content>
                            <v-list-item-title :class="{ 'grey--text': book.book_type == this.BOOK_TYPE.PHYSICAL }">
                                {{ $t('book.convertToAudio') }}
                                <span v-if="audios.status === AUDIO_STATUS.PROCESSING && audios.progress && audios.progress.converted_chapters !== undefined"
                                      class="ml-1 text-caption">
                                    ({{ audios.progress.converted_chapters }}/{{ audios.progress.total_chapters }})
                                </span>
                                <span v-if="audios.status === AUDIO_STATUS.CONVERTED && audios.count > 0"
                                    class="ml-1 text-caption">
                                    ({{ audios.count }})
                                </span>
                            </v-list-item-title>
                        </v-list-item-content>
                        <v-list-item-action>
                            <v-icon>mdi-arrow-right</v-icon>
                        </v-list-item-action>
                    </v-list-item>
                </v-list>
            </v-card>
        </v-col>
    </v-row>

    <v-dialog v-model="dialog_set_cover" persistent max-width="400">
      <v-card>
        <v-card-title>{{ $t('book.setCover') }}</v-card-title>
        <v-card-text>
          <v-file-input
            accept="image/png,image/jpeg"
            :label="$t('book.selectCover')"
            v-model="cover_file"
            show-size
            :error-messages="cover_error"
            filled
          ></v-file-input>
        </v-card-text>
        <v-card-actions>
          <v-btn text @click="dialog_set_cover = false">{{ $t('common.cancel') }}</v-btn>
          <v-spacer></v-spacer>
          <v-btn text color="primary" @click="uploadCover">{{ $t('common.ok') }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <!-- 添加实体书对话框 -->
    <v-dialog v-if="$store.state.sys.allow.physical_books" v-model="isbn_dialog" persistent transition="dialog-bottom-transition" width="410">
        <v-card>
            <v-toolbar flat dense dark color="green">
                <v-icon>mdi-book-plus</v-icon>
                <v-toolbar-title class="ml-2">{{ $t('upload.addPhysicalBook') }}</v-toolbar-title>
                <v-spacer></v-spacer>
                <v-btn color="" text @click="cancelAddBook">{{ $t('upload.close') }}</v-btn>
            </v-toolbar>
            <v-card-title></v-card-title>
            <v-card-text>
                <p class="body-1">{{ $t('upload.addPhysicalBookDesc') }}</p>
                <v-text-field
                    ref="isbnField"
                    v-model="isbn"
                    :label="$t('upload.isbnLabel')"
                    :placeholder="$t('upload.isbnPlaceholder')"
                    outlined
                    :rules="isbnRules"
                    counter
                    maxlength="17"
                    :hint="$t('upload.isbnHint')"
                    persistent-hint
                    autofocus
                    @keyup.enter="confirmAddBook"
                    @input="clearValidationErrors"
                >
                    <template v-slot:prepend-inner>
                        <v-icon>mdi-barcode</v-icon>
                    </template>
                    <template v-slot:append>
                        <v-tooltip bottom>
                            <template v-slot:activator="{ on, attrs }">
                                <v-btn
                                    icon
                                    small
                                    @click="triggerImageUpload"
                                    :loading="recognizing_barcode"
                                    :disabled="recognizing_barcode"
                                    color="primary"
                                    v-bind="attrs"
                                    v-on="on"
                                >
                                    <v-icon>mdi-camera</v-icon>
                                </v-btn>
                            </template>
                            <span>{{ $t('upload.selectImageForBarcode') }}</span>
                        </v-tooltip>
                    </template>
                </v-text-field>

                <!-- 隐藏的文件输入框 -->
                <input
                    ref="barcodeImageInput"
                    type="file"
                    accept="image/*"
                    style="display: none"
                    @change="handleImageUpload"
                />

                <!-- 继续添加checkbox -->
                <v-checkbox
                    v-model="continueAdding"
                    :label="$t('upload.continueAdding')"
                    color="green"
                    class="mt-4"
                ></v-checkbox>
            </v-card-text>
            <v-card-actions>
                <v-spacer></v-spacer>
                <v-btn
                    :loading="adding_book"
                    color="green"
                    @click="confirmAddBook"
                    :disabled="!isValidIsbn"
                >
                    {{ $t('upload.confirmAdd') }}
                </v-btn>
                <v-spacer></v-spacer>
            </v-card-actions>
        </v-card>
    </v-dialog>
  </div>
</template>

<script>
import BookCards from "~/components/BookCards.vue";

export default {
    components: {
        BookCards,
    },
    computed: {
        is_txt(){
          if(!this.book)return false
          let formats=this.book.files.map(x=>x.format.toLowerCase())
          return formats.includes("txt")
        },
        pub_year: function () {
            if (this.book === null || this.book.pubdate == null) {
                return "N/A";
            }
            return this.book.pubdate.split("-")[0];
        },
        tiny: function () {
            return this.$vuetify.breakpoint.xsOnly;
        },
        isFavorite: function () {
            return this.book.state && this.book.state.favorite === 1;
        },
        isWants: function () {
            return this.book.state && this.book.state.wants === 1;
        },
        readingStateButtonText: function () {
            if (!this.book.state) return this.$t('readingState.setReading');
            const readState = this.book.state.read_state;
            if (readState === 1) {
                return this.$t('readingState.setDone');
            } else {
                return this.$t('readingState.setReading');
            }
        },
        readingDaysText: function () {
            if (!this.book.state || !this.book.state.read_date) return '';

            const readDate = new Date(this.book.state.read_date);
            const today = new Date();
            const diffTime = Math.abs(today - readDate);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));

            if (diffDays <= 1) {
                return this.$t('readingState.readingWithinOneDay');
            } else {
                return this.$t('readingState.readingDays', { days: diffDays });
            }
        },
        completedReadingText: function () {
            if (!this.book.state || !this.book.state.read_date) return '';

            const readDate = new Date(this.book.state.read_date);
            const dateStr = readDate.toLocaleDateString();
            return this.$t('readingState.completedReading', { date: dateStr });
        },
        isValidIsbn: function() {
            if (!this.isbn) return false;
            // 移除连字符和空格
            const cleanIsbn = this.isbn.replace(/[-\s]/g, '');
            // 检查是否为10位或13位数字（可能包含X）
            return /^[0-9]{9}[0-9X]$/.test(cleanIsbn) || /^[0-9]{13}$/.test(cleanIsbn);
        },

        // ISBN验证规则
        isbnRules() {
            return [
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    return !!v || this.$t('upload.isbnRequired');
                },
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    return (v && v.length >= 10) || this.$t('upload.isbnMinLength');
                },
                v => {
                    // 如果没有输入内容且没有手动触发验证，不显示错误
                    if (!v && !this.showValidationErrors) {
                        return true;
                    }
                    return (v && /^[0-9\-X]+$/.test(v)) || this.$t('upload.isbnInvalidFormat');
                }
            ];
        }
    },
    data: () => ({
        err: "",
        msg: "",
        book: {id: 0, title: "", files: [], tags: [], pubdate: "", state: {favorite: 0, wants: 0, read_state: 0}},
        audios: {count: 0, files: [], status: "ok"},
        // Audio status constants
        AUDIO_STATUS: {
            UNAVAILABLE: "unavailable",
            AVAILABLE: "available",
            PROCESSING: "processing",
            CONVERTED: "converted",
            FAILED: "failed",
            OK: "ok"
        },
        READING_STATE: {
            UNREAD: 0,
            READING: 1,
            FINISHED: 2
        },
        BOOK_TYPE: {
            EBOOK: 0,
            PHYSICAL: 1
        },
        debug: false,
        loaded: false,
        mail_to: "",
        kindle_sender: "",
        txt_parse_inited: false,
        favoriteLoading: false,
        wantsLoading: false,
        readingStateLoading: false,
        dialog_download: false,
        dialog_epub2audio: false,
        dialog_audiolist: false,
        dialog_refer: false,
        dialog_msg: false,
        dialog_set_cover: false,
        // 添加实体书对话框
        isbn_dialog: false,
        adding_book: false,
        isbn: "",
        continueAdding: false,
        // 条形码识别相关
        recognizing_barcode: false,
        // 控制是否显示验证错误（仅在点击添加按钮时显示）
        showValidationErrors: false,
        cover_file: null,
        cover_error: '',
        refer_books_loading: false,
        refer_books_setting_btn_loading:false,
        refer_books: [],
        epub2audio_processing: false,
        voice_name: "", // 语音名称，将从localStorage加载
        playing_sample: null,
        currentAudio: null,
        // Audio file playback state
        playing_audio_index: null,
        audio_loading: false,
        audio_paused: false,
        currentAudioFile: null,
        // Progress polling timer
        progressTimer: null,
        voice_options: [
            {
                voice_name: "zh-CN-liaoning-XiaobeiNeural",
                display_name: "女声 | 晓北（辽宁）",
                gender: "female",
                sample_file: "female/zh-CN-liaoning-XiaobeiNeural.mp3"
            },
            {
                voice_name: "zh-CN-XiaoxiaoNeural",
                display_name: "女声 | 晓晓",
                gender: "female",
                sample_file: "female/zh-CN-XiaoxiaoNeural.mp3"
            },
            {
                voice_name: "zh-CN-XiaoyiNeural",
                display_name: "女声 | 晓伊",
                gender: "female",
                sample_file: "female/zh-CN-XiaoyiNeural.mp3"
            },
            {
                voice_name: "zh-HK-HiuGaaiNeural",
                display_name: "女声 | 晓佳（香港）",
                gender: "female",
                sample_file: "female/zh-HK-HiuGaaiNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunjianNeural",
                display_name: "男声 | 云健",
                gender: "male",
                sample_file: "male/zh-CN-YunjianNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunxiNeural",
                display_name: "男声 | 云希",
                gender: "male",
                sample_file: "male/zh-CN-YunxiNeural.mp3"
            },
            {
                voice_name: "zh-CN-YunyangNeural",
                display_name: "男声 | 云扬",
                gender: "male",
                sample_file: "male/zh-CN-YunyangNeural.mp3"
            },
            {
                voice_name: "zh-HK-WanLungNeural",
                display_name: "男声 | 云龙（香港）",
                gender: "male",
                sample_file: "male/zh-HK-WanLungNeural.mp3"
            }
        ],
        email_rules: function (email) {
            var re = /^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
            return (email !== this.kindle_sender && re.test(email)) || "Invalid email format";
        },
    }),
    async asyncData({params, app, res}) {
        if (res !== undefined) {
            res.setHeader("Cache-Control", "no-cache");
        }
        return app.$backend(`/book/${params.bookid}`);
    },
    head() {
        return {
            title: this.book.title,
        };
    },
    created() {
        this.init(this.$route);
        this.mail_to = this.$store.state.user.kindle_email;
        this.get_txt_parse_status()
        if (process.client) {
            this.mail_to = this.$cookies.get("last_mailto");
            // 从localStorage获取上次使用的语音名称
            const lastUsedVoice = localStorage.getItem("last_used_voice_name");
            this.voice_name = lastUsedVoice || "zh-CN-XiaoxiaoNeural"; // 如果没有保存的语音，使用默认的晓晓

            // 检查URL参数，如果有continue_adding=true则自动弹出添加对话框
            if (this.$route.query.continue_adding === 'true' && this.$store.state.sys.allow.physical_books) {
                this.$nextTick(() => {
                    this.isbn_dialog = true;
                    this.continueAdding = true;
                });
            }
        } else {
            // 服务端渲染时使用默认语音
            this.voice_name = "zh-CN-XiaoxiaoNeural";
        }
    },
    watch: {
        // 监听audios数据变化，当数据加载完成后检查是否需要启动进度轮询
        audios: {
            handler(newValue, oldValue) {
                if (!newValue || (oldValue && newValue && newValue.status === oldValue.status)) return;
                if (!process.client) return;
                if (this.loaded) return;
                this.loaded = true;
                if (newValue && newValue.status === this.AUDIO_STATUS.PROCESSING) {
                    // 如果音频状态是正在处理中，启动进度轮询
                    this.start_audio_progress_polling();
                }
            },
            immediate: true, // 立即执行一次，用于初始数据检查
            deep: true // 深度监听对象变化
        }
    },
    beforeRouteUpdate(to, from, next) {
        this.init(to, next);
    },
    beforeDestroy() {
        // 清理音频资源
        this.stop_current_audio();
        this.stop_audio_file_playback();
        this.stop_audio_progress_polling();
    },
    methods: {
        async toggleFavorite() {
            if (this.favoriteLoading) return;

            this.favoriteLoading = true;
            try {
                const newFavoriteStatus = !this.isFavorite;
                const response = await this.$backend(`/book/${this.book.id}/favorite`, {
                    method: 'POST',
                    body: JSON.stringify({ favorite: newFavoriteStatus }),
                });

                if (response.err === 'ok') {
                    // 更新本地状态
                    if (!this.book.state) {
                        this.book.state = {};
                    }
                    this.book.state.favorite = newFavoriteStatus ? 1 : 0;
                    this.book.state.favorite_date = newFavoriteStatus ? new Date().toISOString() : null;

                    // 显示成功提示
                    const message = newFavoriteStatus ? '已收藏' : '已取消收藏';
                    this.$alert('success', message);
                } else {
                    this.$alert('error', response.msg || '操作失败');
                }
            } catch (error) {
                console.error('收藏操作失败:', error);
                this.$alert('error', '网络错误，请稍后重试');
            } finally {
                this.favoriteLoading = false;
            }
        },
        async toggleWants() {
            if (this.wantsLoading) return;

            this.wantsLoading = true;
            try {
                const newWantsStatus = !this.isWants;
                const response = await this.$backend(`/book/${this.book.id}/wants`, {
                    method: 'POST',
                    body: JSON.stringify({ wants: newWantsStatus }),
                });

                if (response.err === 'ok') {
                    // 更新本地状态
                    if (!this.book.state) {
                        this.book.state = {};
                    }
                    this.book.state.wants = newWantsStatus ? 1 : 0;
                    this.book.state.wants_date = newWantsStatus ? new Date().toISOString() : null;

                    // 显示成功提示
                    const message = newWantsStatus ? '已添加到待读清单' : '已从待读清单中移除';
                    this.$alert('success', message);
                } else {
                    this.$alert('error', response.msg || '操作失败');
                }
            } catch (error) {
                console.error('待读操作失败:', error);
                this.$alert('error', '网络错误，请稍后重试');
            } finally {
                this.wantsLoading = false;
            }
        },
        async handleReadingStateChange() {
            if (this.readingStateLoading) return;

            this.readingStateLoading = true;
            try {
                // 确定要设置的新状态
                let newReadState;
                let successMessage;

                if (!this.book.state || this.book.state.read_state === this.READING_STATE.UNREAD || this.book.state.read_state === this.READING_STATE.FINISHED) {
                    // 未读或已读完 -> 设为在读
                    newReadState = this.READING_STATE.READING;
                    successMessage = '已设置为在读状态';
                } else if (this.book.state.read_state === this.READING_STATE.READING) {
                    // 在读 -> 设为读完
                    newReadState = this.READING_STATE.FINISHED;
                    successMessage = '已标记为读完';
                }

                const response = await this.$backend(`/book/${this.book.id}/readstate`, {
                    method: 'POST',
                    body: JSON.stringify({ read_state: newReadState }),
                });

                if (response.err === 'ok') {
                    // 更新本地状态
                    if (!this.book.state) {
                        this.book.state = {};
                    }
                    this.book.state.read_state = newReadState;
                    this.book.state.read_date = new Date().toISOString();
                    if (newReadState === this.READING_STATE.READING) {
                        this.book.state.wants = 0; // 在读后自动移除待读状态
                    }

                    // 显示成功提示
                    this.$alert('success', successMessage);
                } else {
                    this.$alert('error', response.msg || '操作失败');
                }
            } catch (error) {
                console.error('设置阅读状态失败:', error);
                this.$alert('error', '网络错误，请稍后重试');
            } finally {
                this.readingStateLoading = false;
            }
        },
        init(route, next) {
            this.$store.commit("navbar", true);
            var rsp = this;
            if (rsp.err !== "ok") {
                this.$alert("error", rsp.msg, "/");
            }
            if (next) next();
        },
        switch_to_audio_player() {
            if (this.audios.status === this.AUDIO_STATUS.CONVERTED && this.audios.count > 0) {
                // 切换到音频播放页面, /audio/<bid>
                this.$router.push("/audio/" + this.book.id);
            } else {
                this.switch_audio_dialog();
            }
        },
        switch_audio_dialog() {
            // 如果是实体书，则不允许转换音频
            if (this.book.book_type == this.BOOK_TYPE.PHYSICAL) {
                return;
            }

            if (this.audios.status === this.AUDIO_STATUS.UNAVAILABLE || this.audios.status === this.AUDIO_STATUS.FAILED) {
                this.dialog_epub2audio = !this.dialog_epub2audio
            } else {
                this.dialog_audiolist = !this.dialog_audiolist
                // Start progress polling when opening audio list dialog
                if (this.dialog_audiolist && this.audios.status === this.AUDIO_STATUS.PROCESSING) {
                    this.start_audio_progress_polling();
                } else {
                    this.stop_audio_progress_polling();
                }
            }
        },
        sendto_kindle() {
            if (process.client) {
                this.$cookies.set("last_mailto", this.mail_to);
            }
            this.$backend("/book/" + this.book.id + "/push", {
                method: "POST",
                body: "mail_to=" + this.mail_to,
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            }).then((rsp) => {
                this.dialog_epub2audio = false;
                if (rsp.err === "ok") {
                    this.$alert("success", rsp.msg, "#");
                } else {
                    this.$alert("error", rsp.msg, "#");
                }
            });
        },
        generate_audio() {
            // 保存选择的语音名称到localStorage
            if (process.client) {
                localStorage.setItem("last_used_voice_name", this.voice_name);
            }

            this.$backend(`/audio/${this.book.id}/conversion`, {
                method: "POST",
                body: JSON.stringify({voice: this.voice_name}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.epub2audio_processing = true;
                    this.dialog_epub2audio = false;
                    this.start_audio_progress_polling();
                    this.$alert("success", this.$t('book.audioGenerated'));
                } else {
                    this.stop_audio_progress_polling();
                    this.$alert("error", rsp.msg);
                }
            });
        },
        get_txt_parse_status(){
          this.$backend(`/book/txt/init?id=${this.book.id}&test=1`,)
            .then(res => {
              if (res.err === "ok" && res.msg === "已解析") {
                this.txt_parse_inited = true;
              }
            })
        },
        get_refer() {
            this.dialog_refer = true;
            this.refer_books_loading = true;
            this.$backend("/book/" + this.book.id + "/refer")
                .then((rsp) => {
                    this.refer_books = rsp.books.map((b) => {
                        b.href = "";
                        b.img = "/get/pcover?url=" + encodeURIComponent(b.cover_url);
                        return b;
                    });
                })
                .finally(() => {
                    this.refer_books_loading = false;
                });
        },
        set_refer(provider_key, provider_value, opt) {
            // 防止多次重复点击
            if(this.refer_books_setting_btn_loading) return;
            // 显示加载条提示
            this.refer_books_setting_btn_loading = true;
            var data = new URLSearchParams(opt);
            data.append("provider_key", provider_key);
            data.append("provider_value", provider_value);
            this.$backend("/book/" + this.book.id + "/refer", {
                method: "POST",
                body: data,
            }).then((rsp) => {
                this.dialog_refer = false;
                if (rsp.err === "ok") {
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                    this.$alert("success", "设置成功！");
                } else {
                    this.$alert("error", rsp.msg);
                }
                this.init(this.$route);
            }).finally(()=>{
               //关闭加载条提示
               this.refer_books_setting_btn_loading = false;
            });
        },
        reset_refer() {
            // 使用本地书籍信息覆盖
            this.$backend("/book/" + this.book.id + "/refer", {
                method: "POST",
                body: new URLSearchParams({reset: "yes"}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", this.$t('book.resetSuccessful'));
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        convert_book() {
            // 转换书籍格式
            this.$backend("/book/" + this.book.id + "/convert", {
                method: "POST",
                body: new URLSearchParams({reset: "yes"}),
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", this.$t('book.convertSuccessful'));
                    this.$router.push("/book/" + this.book.id);
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        set_sole() {
            // 设置为私藏
            this.$backend("/book/" + this.book.id + "/setsole", {
                method: "POST",
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", "设置成功");
                    this.$router.push("/book/" + this.book.id);
                    location.reload();
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        delete_book() {
            this.$backend("/book/" + this.book.id + "/delete", {
                method: "POST",
            }).then((rsp) => {
                if (rsp.err === "ok") {
                    this.$alert("success", "删除成功");
                    this.$router.push("/");
                } else {
                    this.$alert("error", rsp.msg);
                }
            });
        },
        play_sample_voice(voice_option) {
            if (this.playing_sample === voice_option.voice_name) {
                // 如果正在播放相同的样本，则停止播放
                this.stop_current_audio();
                return;
            }

            // 停止当前播放的音频
            this.stop_current_audio();

            // 设置正在播放状态
            this.playing_sample = voice_option.voice_name;

            // 创建音频对象并播放
            const audioUrl = `/static/epub_to_audio/samples/chinese/${voice_option.sample_file}`;
            this.currentAudio = new Audio(audioUrl);

            this.currentAudio.addEventListener('ended', () => {
                this.playing_sample = null;
                this.currentAudio = null;
            });

            this.currentAudio.addEventListener('error', () => {
                this.playing_sample = null;
                this.currentAudio = null;
                this.$alert("error", "音频文件加载失败");
            });

            this.currentAudio.play().catch(() => {
                this.playing_sample = null;
                this.currentAudio = null;
                this.$alert("error", "音频播放失败");
            });
        },
        stop_current_audio() {
            if (this.currentAudio) {
                this.currentAudio.pause();
                this.currentAudio = null;
            }
            this.playing_sample = null;
        },
        play_audio_file(audio_item, index) {
            // If clicking on the same audio that's currently playing
            if (this.playing_audio_index === index && this.currentAudioFile) {
                if (this.audio_paused) {
                    // Resume playback
                    this.currentAudioFile.play();
                    this.audio_paused = false;
                } else {
                    // Pause playback
                    this.currentAudioFile.pause();
                    this.audio_paused = true;
                }
                return;
            }

            // Stop any currently playing audio
            this.stop_audio_file_playback();

            // Stop sample voice if playing
            this.stop_current_audio();

            // Set loading state
            this.audio_loading = true;
            this.playing_audio_index = index;

            // Create new audio object
            this.currentAudioFile = new Audio(audio_item.url);

            this.currentAudioFile.addEventListener('loadstart', () => {
                this.audio_loading = true;
            });

            this.currentAudioFile.addEventListener('canplay', () => {
                this.audio_loading = false;
            });

            this.currentAudioFile.addEventListener('ended', () => {
                this.stop_audio_file_playback();
            });

            this.currentAudioFile.addEventListener('error', () => {
                this.stop_audio_file_playback();
                this.$alert("error", "音频文件加载失败");
            });

            // Start playback
            this.currentAudioFile.play().then(() => {
                this.audio_loading = false;
                this.audio_paused = false;
            }).catch(() => {
                this.stop_audio_file_playback();
                this.$alert("error", "音频播放失败");
            });
        },
        stop_audio_file_playback() {
            if (this.currentAudioFile) {
                this.currentAudioFile.pause();
                this.currentAudioFile = null;
            }
            this.playing_audio_index = null;
            this.audio_loading = false;
            this.audio_paused = false;
        },
        start_audio_progress_polling() {
            this.stop_audio_progress_polling(); // Clear any existing timer
            this.progressTimer = setInterval(() => {
                this.update_audio_progress();
            }, 10000); // Poll every 10 seconds
        },
        stop_audio_progress_polling() {
            if (this.progressTimer) {
                clearInterval(this.progressTimer);
                this.progressTimer = null;
            }
        },
        async update_audio_progress() {
            try {
                const response = await this.$backend(`/book/${this.book.id}`);
                if (response.audios) {
                    this.audios = response.audios;

                    // Stop polling if conversion is complete or failed
                    if (this.audios.status !== this.AUDIO_STATUS.PROCESSING) {
                        this.stop_audio_progress_polling();
                    }
                }
            } catch (error) {
                console.error('Failed to update audio progress:', error);
                // Continue polling even if one request fails
            }
        },
        async clear_conversion() {
            try {
                let endpoint;
                let successMessage;

                if (this.audios.status === this.AUDIO_STATUS.PROCESSING) {
                    // Cancel the conversion
                    endpoint = `/audio/${this.book.id}/cancel`;
                    successMessage = this.$t('book.conversionCancelled');
                } else if (this.audios.status === this.AUDIO_STATUS.CONVERTED) {
                    // Delete the audio files
                    endpoint = `/audio/${this.book.id}/delete`;
                    successMessage = this.$t('book.audioFilesDeleted');
                } else {
                    return; // No action needed for other statuses
                }

                const response = await this.$backend(endpoint, {
                    method: "POST"
                });

                if (response.err === 'ok') {
                    this.$alert('success', successMessage);
                    // Stop any ongoing polling
                    this.stop_audio_progress_polling();
                    // Close the dialog
                    this.dialog_audiolist = false;
                    // Reset audio status
                    this.audios = {count: 0, files: [], status: "unavailable"};
                } else {
                    this.$alert("error", response.msg || "操作失败");
                }
            } catch (error) {
                console.error('Failed to clear conversion:', error);
                this.$alert("error", "操作失败，请稍后重试");
            }
        },
        uploadCover() {
          this.cover_error = '';
          if (!this.cover_file) {
            this.cover_error = this.$t('book.noCoverSelected');
            return;
          }
          const file = this.cover_file;
          if (file.size > 1024 * 1024) {
            this.cover_error = this.$t('book.coverTooLarge');
            return;
          }
          const type = file.type;
          if (type !== 'image/jpeg' && type !== 'image/png') {
            this.cover_error = this.$t('book.coverTypeInvalid');
            return;
          }
          const form = new FormData();
          form.append('cover_data', file);
          this.$backend(`/book/${this.book.id}/cover`, {
            method: 'POST',
            body: form,
          }).then(resp => {
            if (resp.err === 'ok') {
              this.dialog_set_cover = false;
              location.reload();
            } else {
              this.cover_error = resp.msg || this.$t('book.coverUploadFailed');
            }
          });
        },

        // 添加实体书相关方法
        cancelAddBook() {
            this.isbn_dialog = false;
            this.isbn = "";
            this.continueAdding = false; // 重置checkbox状态
            // 重置验证状态
            this.showValidationErrors = false;
        },

        confirmAddBook() {
            // 触发验证显示
            this.showValidationErrors = true;

            // 等待下一个tick让验证生效，然后检查表单有效性
            this.$nextTick(() => {
                // 检查ISBN是否有效
                if (!this.isbn) {
                    this.$alert("error", this.$t('upload.isbnRequired'));
                    return;
                }

                if (!this.isValidIsbn) {
                    this.$alert("error", this.$t('upload.invalidIsbn'));
                    return;
                }

                this.adding_book = true;
                // 清理ISBN号（移除连字符和空格）
                const cleanIsbn = this.isbn.replace(/[-\s]/g, '');

                this.$backend("/book/add", {
                    method: "POST",
                    body: JSON.stringify({
                        isbn: cleanIsbn,
                    }),
                })
                .then((rsp) => {
                    this.isbn_dialog = false;
                    if (rsp.err != "ok") {
                        this.$alert("error", rsp.msg);
                    } else {
                        // 如果勾选了继续添加，则跳转时携带参数，否则直接跳转
                        if (this.continueAdding) {
                            this.$router.push(`/book/${rsp.book_id}?continue_adding=true`);
                        } else {
                            this.$alert("success", rsp.msg || this.$t('upload.bookAdded'));
                            this.$router.push(`/book/${rsp.book_id}`);
                        }
                    }
                })
                .catch((error) => {
                    this.$alert("error", "添加图书时发生错误: " + error.message);
                })
                .finally(() => {
                    this.adding_book = false;
                    this.isbn = "";
                    // 只有在不继续添加的情况下才重置checkbox
                    if (!this.continueAdding) {
                        this.continueAdding = false;
                    }
                });
            });
        },

        // 清除验证错误显示状态
        clearValidationErrors() {
            // 如果用户开始重新输入，重置验证错误显示状态
            if (this.isbn && this.showValidationErrors) {
                this.showValidationErrors = false;
            }
        },

        // 触发图片上传
        triggerImageUpload() {
            this.$refs.barcodeImageInput.click();
        },

        // 处理图片上传和条形码识别
        handleImageUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            // 检查文件类型
            if (!file.type.startsWith('image/')) {
                this.$alert("error", "请选择图片文件");
                return;
            }

            // 检查文件大小（限制为10MB）
            if (file.size > 10 * 1024 * 1024) {
                this.$alert("error", "图片文件不能超过10MB");
                return;
            }

            this.recognizing_barcode = true;

            // 创建FormData对象
            const formData = new FormData();
            formData.append('barcode_image', file);

            // 调用后端API识别条形码
            this.$backend('/admin/barcode', {
                method: 'POST',
                body: formData,
            })
            .then(response => {
                if (response.err === 'ok') {
                    // 识别成功，填充ISBN字段
                    this.isbn = response.isbn;
                    // 触发验证
                    this.$nextTick(() => {
                        this.$refs.isbnField && this.$refs.isbnField.validate();
                    });
                } else if (response.err === 'no_barcode') {
                    this.$alert("error", "未在图片中识别到条形码，请确保图片清晰且包含条形码");
                } else if (response.err === 'no_isbn') {
                    this.$alert("warning", response.msg);
                } else {
                    this.$alert("error", response.msg || "条形码识别失败");
                }
            })
            .catch(error => {
                console.error('条形码识别错误:', error);
                this.$alert("error", "条形码识别服务出错，请稍后重试");
            })
            .finally(() => {
                this.recognizing_barcode = false;
                // 清空文件输入框，允许重复选择同一文件
                event.target.value = '';
            });
        },
    },
};
</script>

<style>
/* Flat style scrollbar for audio list */
.audio-scroll-container {
    scrollbar-width: thin;
    scrollbar-color: #cccccc #f1f1f1;
}

.audio-scroll-container::-webkit-scrollbar {
    width: 8px;
}

.audio-scroll-container::-webkit-scrollbar-track {
    background: #f1f1f1;
    border-radius: 0;
}

.audio-scroll-container::-webkit-scrollbar-thumb {
    background: #cccccc;
    border-radius: 0;
    border: none;
}

.audio-scroll-container::-webkit-scrollbar-thumb:hover {
    background: #999999;
}

.audio-scroll-container::-webkit-scrollbar-corner {
    background: #f1f1f1;
}


.align-right {
    text-align: right;
}

.book-footer {
    padding-top: 0;
    padding-bottom: 3px;
}

.tag-chips a {
    margin: 4px 2px;
}

.book-comments {
    /*text-indent: 2em;*/
    overflow: hidden;
    display: -webkit-box;
    line-clamp: 3;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    text-overflow: clip;
    margin-top: 6px;
    text-align: left;
}

.book-comments p {
    font-size: small;
    margin-bottom: 0;
}

h1.book-detail-title {
    line-height: inherit;
}

/* Flat style scrollbar for audio list */
.audio-scroll-container {
    scrollbar-width: thin;
    scrollbar-color: #cccccc #f1f1f1;
}

.audio-scroll-container::-webkit-scrollbar {
    width: 8px;
}

.audio-scroll-container::-webkit-scrollbar-track {
    background: #f1f1f1;
    border-radius: 0;
}

.audio-scroll-container::-webkit-scrollbar-thumb {
    background: #cccccc;
    border-radius: 0;
    border: none;
}

.audio-scroll-container::-webkit-scrollbar-thumb:hover {
    background: #999999;
}

.audio-scroll-container::-webkit-scrollbar-corner {
    background: #f1f1f1;
}

/* Dialog border styles */
.dialog-border {
    border: 2px solid #e0e0e0 !important;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
    border-radius: 8px !important;
}

.dialog-border .v-card__title {
    border-bottom: 1px solid #e0e0e0;
}
</style>
