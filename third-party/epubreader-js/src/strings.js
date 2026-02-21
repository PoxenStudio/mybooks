export class Strings {

	constructor(reader) {

		this.language = reader.settings.language || "en";
		this.values = {
			en: {
				"toolbar/sidebar": "Sidebar",
				"toolbar/prev": "Previous page",
				"toolbar/next": "Next page",
				"toolbar/openbook": "Open book",
				"toolbar/openbook/error": "Your browser does not support the required features.\nPlease use a modern browser such as Google Chrome, or Mozilla Firefox.",
				"toolbar/bookmark": "Add this page to bookmarks",
				"toolbar/fullscreen": "Fullscreen",

				"sidebar/close": "Close Sidebar",
				"sidebar/contents": "Contents",
				"sidebar/bookmarks": "Bookmarks",
				"sidebar/bookmarks/add": "Add",
				"sidebar/bookmarks/remove": "Remove",
				"sidebar/bookmarks/clear": "Clear",
				"sidebar/annotations": "Annotations",
				"sidebar/annotations/add": "Add",
				"sidebar/annotations/remove": "Remove",
				"sidebar/annotations/clear": "Clear",
				"sidebar/annotations/anchor": "Anchor",
				"sidebar/annotations/cancel": "Cancel",
				"sidebar/search": "Search",
				"sidebar/search/placeholder": "Search",
				"sidebar/settings": "Settings",
				"sidebar/settings/language": "Language",
				"sidebar/settings/font": "Font",
				"sidebar/settings/font/default": "Default",
				"sidebar/settings/fontsize": "Font size (%)",
				"sidebar/settings/flow": "Flow",
				"sidebar/settings/pagination": ["Pagination", "Generate pagination"],
				"sidebar/settings/spread": "Spread",
				"sidebar/settings/spread/items": ["None", "Auto"],
				"sidebar/settings/spread/minwidth": "Minimum spread width",
				"sidebar/settings/theme": "Theme",
				"sidebar/settings/theme/items": ["Light", "Dark", "Eye Care"],
				"sidebar/metadata": "Metadata",
				"sidebar/metadata/title": "Title",
				"sidebar/metadata/creator": "Creator",
				"sidebar/metadata/description": "Description",
				"sidebar/metadata/pubdate": "Pubdate",
				"sidebar/metadata/publisher": "Publisher",
				"sidebar/metadata/identifier": "Identifier",
				"sidebar/metadata/language": "Language",
				"sidebar/metadata/rights": "Rights",
				"sidebar/metadata/modified_date": "Modified date",
				"sidebar/metadata/layout": "Layout", // rendition:layout
				"sidebar/metadata/flow": "Flow", // rendition:flow
				"sidebar/metadata/spread": "Spread", // rendition:spread
				"sidebar/metadata/direction": "Direction", // page-progression-direction

				"notedlg/label": "Note",
				"notedlg/add": "Add"
			},
			zh: {
				"toolbar/sidebar": "侧边栏",
				"toolbar/prev": "上一页",
				"toolbar/next": "下一页",
				"toolbar/openbook": "打开书籍",
				"toolbar/openbook/error": "您的浏览器不支持所需功能。\n请使用现代浏览器如谷歌Chrome或火狐Firefox。",
				"toolbar/bookmark": "加为书签",
				"toolbar/fullscreen": "全屏",

				"sidebar/close": "关闭侧边栏",
				"sidebar/contents": "目录",
				"sidebar/bookmarks": "书签",
				"sidebar/bookmarks/add": "添加",
				"sidebar/bookmarks/remove": "移除",
				"sidebar/bookmarks/clear": "清空",
				"sidebar/annotations": "注解",
				"sidebar/annotations/add": "添加",
				"sidebar/annotations/remove": "移除",
				"sidebar/annotations/clear": "清空",
				"sidebar/annotations/anchor": "锚定",
				"sidebar/annotations/cancel": "取消",

				"sidebar/search": "搜索",
				"sidebar/search/placeholder": "搜索",
				"sidebar/settings": "设置",
				"sidebar/settings/language": "语言",
				"sidebar/settings/font": "字体",
				"sidebar/settings/font/default": "默认字体",
				"sidebar/settings/fontsize": "字体大小 (%)",
				"sidebar/settings/flow": "换页", // Scrolled = "滚动模式"
				"sidebar/settings/pagination": ["分页模式", "滚动模式"],
				"sidebar/settings/spread": "双页布局",
				"sidebar/settings/spread/items": ["无", "自动"],
				"sidebar/settings/spread/minwidth": "最小双页宽度",
				"sidebar/settings/theme": "颜色主题",
				"sidebar/settings/theme/items": ["亮色", "暗色", "护眼"],
				"sidebar/metadata": "元数据",
				"sidebar/metadata/title": "标题",
				"sidebar/metadata/creator": "作者",
				"sidebar/metadata/description": "描述",
				"sidebar/metadata/pubdate": "出版日期",
				"sidebar/metadata/publisher": "出版商",
				"sidebar/metadata/identifier": "标识符",
				"sidebar/metadata/language": "语言",
				"sidebar/metadata/rights": "版权",
				"sidebar/metadata/modified_date": "修改日期",
				"sidebar/metadata/layout": "布局",  // rendition:layout
				"sidebar/metadata/flow": "流模式",  // rendition:flow
				"sidebar/metadata/spread": "双页布局",  // rendition:spread
				"sidebar/metadata/direction": "阅读方向",  // page-progression-direction

				"notedlg/label": "笔记",
				"notedlg/add": "添加"
			},
		};

		reader.on("languagechanged", (value) => {
			this.language = value;
		});
	}

	get(key) { return this.values[this.language][key] || "???"; }
}