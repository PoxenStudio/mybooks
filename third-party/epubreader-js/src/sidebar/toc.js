import { UIPanel, UIDiv, UIItem, UIList, UILink, UISpan, UIText, UIBox } from "../ui.js";

export class TocPanel extends UIPanel {

	constructor(reader) {

		super();
		const container = new UIDiv().setClass("list-container");
		const strings = reader.strings;
		const keys = [
			"sidebar/contents"
		];
		const label = new UIText(strings.get(keys[0])).setClass("label");
		this.reader = reader;
		this.selector = undefined; // save reference to selected tree item
		this.setId("contents");
		this.add(new UIBox(label).addClass("header"));

		//-- events --//

		reader.on("navigation", (toc) => {

			container.clear();
			container.add(this.generateToc(toc));
			this.add(container);
		});

		reader.on("languagechanged", (value) => {

			label.setValue(strings.get(keys[0]));
		});
	}

	generateToc(toc, parent) {

		const list = new UIList(parent);

		toc.forEach((chapter) => {

			const link = new UILink(chapter.href, chapter.label);
			const item = new UIItem(list).setId(chapter.id);
			const ibtn = new UISpan();

			link.dom.onclick = (e) => {

				if (this.selector && this.selector !== item)
					this.selector.unselect();

				item.select();
				this.selector = item;
				this.reader.settings.sectionId = chapter.id;
				this.reader.rendition.display(chapter.href);
				e.preventDefault();
			};
			item.add([ibtn, link]);
			this.reader.navItems[chapter.href] = {
				id: chapter.id,
				label: chapter.label
			};

			if (this.reader.settings.sectionId === chapter.id) {
				list.expand();
				item.select();
				this.selector = item;
			}

			if (chapter.subitems && chapter.subitems.length > 0) {

				const subItems = this.generateToc(chapter.subitems, item);
				ibtn.setClass("toggle-collapsed");
				ibtn.dom.onclick = () => {

					if (subItems.expanded) {
						subItems.collaps();
						ibtn.setClass("toggle-collapsed");
					} else {
						subItems.expand();
						ibtn.setClass("toggle-expanded");
					}
					return false;
				};
				item.add(subItems);
			}

			list.add(item);
		});

		return list;
	}
}