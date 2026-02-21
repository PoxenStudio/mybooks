import { UIPanel, UIDiv, UIRow, UIInput, UILink, UIList, UIItem, UIText, UIBox, UISpan } from "../ui.js";

export class BookmarksPanel extends UIPanel {

	constructor(reader) {

		super();
		const container = new UIDiv().setClass("list-container");
		const strings = reader.strings;
		const keys = [
			"sidebar/bookmarks",
			"sidebar/bookmarks/clear"
		];
		const headerLabel = new UIText(strings.get(keys[0])).setClass("label");
		const clearBtn = new UIInput("button", strings.get(keys[1]));
		clearBtn.dom.onclick = (e) => {

			this.clearBookmarks();
			reader.emit("bookmarked", false);
			e.preventDefault();
		};
		this.add(new UIBox([headerLabel, clearBtn]).addClass("header"));
		this.selector = undefined;
		this.bookmarks = new UIList();
		container.add(this.bookmarks);
		this.setId("bookmarks");
		this.add(container);
		this.reader = reader;

		const update = () => {

			clearBtn.dom.disabled = reader.settings.bookmarks.length === 0;
		};

		//-- events --//

		reader.on("displayed", (renderer, cfg) => {

			cfg.bookmarks.forEach((cfi) => {

				this.setBookmark(cfi);
			});
			update();
		});

		reader.on("relocated", (location) => {

			this.locationCfi = location.start.cfi; // save location cfi
		});

		reader.on("bookmarked", (boolean, cfi) => {

			if (boolean) {
				this.appendBookmark();
			} else {
				this.removeBookmark(cfi);
			}
			update();
		});

		reader.on("languagechanged", (value) => {

			headerLabel.setValue(strings.get(keys[0]));
			clearBtn.setValue(strings.get(keys[1]));
		});
	}

	appendBookmark() {

		const cfi = this.locationCfi;
		if (this.reader.isBookmarked(cfi) > -1) {
			return;
		}
		this.setBookmark(cfi);
		this.reader.settings.bookmarks.push(cfi);
	}

	removeBookmark(cfi) {

		const _cfi = cfi || this.locationCfi;
		const index = this.reader.isBookmarked(_cfi);
		if (index === -1) {
			return;
		}
		this.bookmarks.remove(index);
		this.reader.settings.bookmarks.splice(index, 1);
	}

	clearBookmarks() {

		this.bookmarks.clear();
		this.reader.settings.bookmarks = [];
	}

	setBookmark(cfi) {

		const link = new UILink();
		const item = new UIItem();
		const btnr = new UISpan().setClass("btn-remove");
		const navItem = this.reader.navItemFromCfi(cfi);
		let idref;
		let label;

		if (navItem === undefined) {
			const spineItem = this.reader.book.spine.get(cfi);
			idref = spineItem.idref;
			label = spineItem.idref
		} else {
			idref = navItem.id;
			label = navItem.label;
		}

		link.setHref("#" + cfi);
		link.dom.onclick = (e) => {

			if (this.selector && this.selector !== item) {
				this.selector.unselect();
			}
			item.select();
			this.selector = item;
			this.reader.rendition.display(cfi);
			e.preventDefault();
		};
		link.setTextContent(label);

		btnr.dom.onclick = (e) => {

			this.reader.emit("bookmarked", false, cfi);
			e.preventDefault();
		};

		item.add([link, btnr]);
		item.setId(idref);
		this.bookmarks.add(item);
	}
}