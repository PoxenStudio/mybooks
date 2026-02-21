import { UIPanel, UIDiv, UIInput, UILink, UIList, UIItem, UIBox } from "../ui.js";

export class SearchPanel extends UIPanel {

	constructor(reader) {

		super();
		const container = new UIDiv().setClass("list-container");
		const strings = reader.strings;

		let searchQuery = undefined;
		const search = new UIInput("search").setId("nav-q");
		search.dom.placeholder = strings.get("sidebar/search/placeholder");
		search.dom.onsearch = () => {

			const value = search.getValue();

			if (value.length === 0) {
				this.items.clear();
			} else if (searchQuery !== value) {
				this.items.clear();
				this.doSearch(value).then(results => {

					results.forEach(data => {
						this.set(data);
					});
				});
			}
			searchQuery = value;
		};

		this.setId("search");
		this.items = new UIList();
		container.add(this.items);
		this.add([new UIBox(search), container]);
		this.reader = reader;
		this.selector = undefined;
		//
		// improvement of the highlighting of keywords is required...
		//
	}

	/**
	 * Searching the entire book
	 * @param {*} q Query keyword
	 * @returns The search result array.
	 */
	async doSearch(q) {

		const book = this.reader.book;
		const results = await Promise.all(
			book.spine.spineItems.map(item => item.load(book.load.bind(book))
				.then(item.find.bind(item, q)).finally(item.unload.bind(item))));
		return await Promise.resolve([].concat.apply([], results));
	}

	set(data) {

		const link = new UILink("#" + data.cfi, data.excerpt);
		const item = new UIItem();
		link.dom.onclick = () => {

			if (this.selector && this.selector !== item)
				this.selector.unselect();
			
			item.select();
			this.selector = item;
			this.reader.rendition.display(data.cfi);
			return false;
		};
		item.add(link);
		this.items.add(item);
	}
}