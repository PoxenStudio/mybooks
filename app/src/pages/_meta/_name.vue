<script>
 // don't create a template for the section
import ListBook from '~/pages/ListBook.vue'
ListBook.head = function() {
    // 同 ListBook.getPageTitle：vue-router 已解码过 :name，不能再解码第二次
    var name = this.$route.params.name || '';
    var titles = {
        tag: this.$t('meta.tag', { name }),
        series: this.$t('meta.series', { name }),
        rating: this.$t('meta.rating', { name }),
        author: this.$t('meta.author', { name }),
        publisher: this.$t('meta.publisher', { name }),
        keyword: this.$t('meta.keyword', { name }),
    }
    var meta = this.$route.path.split("/")[1];
    if ( titles[meta] !== undefined ) {
        return {
            title: titles[meta]
        }
    }
    return {}
}
export default ListBook
</script>
