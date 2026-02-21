import { UIBox, UIDiv, UIItem, UIList, UIPanel, UIText } from "../ui.js";

export class MetadataPanel extends UIPanel {

	constructor(reader) {

		super();
		const container = new UIDiv().setClass("list-container");
		const strings = reader.strings;
		const labels = {};
		const key = "sidebar/metadata";
		const label = new UIText(strings.get(key)).setClass("label");
		this.add(new UIBox(label).addClass("header"));
		labels[key] = label;

		this.items = new UIList();
		this.setId("metadata");
		this.add(container);

		const init = (prop, meta) => {
			if (meta[prop] === undefined ||
				meta[prop] === null || (typeof meta[prop] === "string" && meta[prop].length === 0)) {
				return;
			}
			const item = new UIItem();
			const label = new UIText().setClass("label");
			const value = new UIText().setClass("value");
			label.setValue(strings.get(key + "/" + prop).toUpperCase());
			if (prop === "description") {
				value.dom.innerHTML = meta[prop];
			} else {
				value.setValue(meta[prop]);
			}
			labels[key + "/" + prop] = label;
			item.add([label, value]);
			this.items.add(item);
		}

		//-- events --//

		reader.on("metadata", (meta) => {

			this.items.clear();
			container.clear();
			container.add(this.items);
			document.title = meta.title;
			for (const prop in meta) {
				init(prop, meta);
			}
		});

		reader.on("languagechanged", (value) => {

			for (const prop in labels) {
				let text;
				if (prop === key) {
					text = strings.get(prop);
				} else {
					text = strings.get(prop).toUpperCase();
				}
				labels[prop].setValue(text);
			}
		});
	}
}