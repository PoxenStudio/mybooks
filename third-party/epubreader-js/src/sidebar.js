import { UITabbedPanel, UIInput, UIDiv } from "./ui.js";
import { TocPanel } from "./sidebar/toc.js";
import { BookmarksPanel } from "./sidebar/bookmarks.js";
import { AnnotationsPanel } from "./sidebar/annotations.js";
import { SearchPanel } from "./sidebar/search.js";
import { SettingsPanel } from "./sidebar/settings.js";
import { MetadataPanel } from "./sidebar/metadata.js";

export class Sidebar {

	constructor(reader) {

		const strings = reader.strings;
		const controls = reader.settings;
		const keys = [
			"sidebar/close",
			"sidebar/contents",
			"sidebar/bookmarks",
			"sidebar/annotations",
			"sidebar/search",
			"sidebar/settings",
			"sidebar/metadata"
		];

		const container = new UITabbedPanel("vertical").setId("sidebar");

		const openerBox = new UIDiv().setId("btn-p").addClass("box");
		const openerBtn = new UIInput("button");
		openerBtn.setTitle(strings.get(keys[0]));
		openerBtn.dom.onclick = (e) => {

			reader.emit("sidebaropener", false);
			e.preventDefault();
			openerBtn.dom.blur();
		};
		openerBox.add(openerBtn);
		container.addMenu(openerBox);

		container.addTab("btn-t", strings.get(keys[1]), new TocPanel(reader));
		if (controls.bookmarks) {
			container.addTab("btn-d", strings.get(keys[2]), new BookmarksPanel(reader));
		}
		if (controls.annotations) {
			container.addTab("btn-a", strings.get(keys[3]), new AnnotationsPanel(reader));
		}
		container.addTab("btn-s", strings.get(keys[4]), new SearchPanel(reader));
		container.addTab("btn-c", strings.get(keys[5]), new SettingsPanel(reader));
		container.addTab("btn-i", strings.get(keys[6]), new MetadataPanel(reader));
		container.select("btn-t");

		document.body.appendChild(container.dom);

		//-- events --//

		reader.on("sidebaropener", (value) => {

			if (value) {
				container.setClass("open");
			} else {
				container.removeAttribute("class");
			}
		});

		reader.on("languagechanged", (value) => {

			openerBtn.setTitle(strings.get(keys[0]));
			container.setLabel("btn-t", strings.get(keys[1]));
			if (controls.bookmarks) {
				container.setLabel("btn-d", strings.get(keys[2]));
			}
			if (controls.annotations) {
				container.setLabel("btn-a", strings.get(keys[3]));
			}
			container.setLabel("btn-s", strings.get(keys[4]));
			container.setLabel("btn-c", strings.get(keys[5]));
			container.setLabel("btn-i", strings.get(keys[6]));
		});
	}
}