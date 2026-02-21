import { UIPanel, UIDiv, UITextArea, UIInput, UILink, UIList, UIItem, UISpan, UIText, UIBox } from "../ui.js";

export class AnnotationsPanel extends UIPanel {

	constructor(reader) {

		super();
		const container = new UIDiv().setClass("list-container");
		const strings = reader.strings;
		const keys = [
			"sidebar/annotations",
			"sidebar/annotations/clear"
		];
		const headerLabel = new UIText(strings.get(keys[0])).setClass("label");
		const clearBtn = new UIInput("button", strings.get(keys[1]));
		clearBtn.dom.onclick = (e) => {

			this.clearNotes();
			e.preventDefault();
		};
		this.add(new UIBox([headerLabel, clearBtn]).addClass("header"));
		this.selector = undefined;
		this.notes = new UIList();
		container.add(this.notes);
		this.setId("annotations");
		this.add(container);
		this.reader = reader;
		this.update = () => {

			clearBtn.dom.disabled = reader.settings.annotations.length === 0;
		};

		//-- events --//

		reader.on("bookready", (cfg) => {

			cfg.annotations.forEach((note) => {

				this.set(note);
			});
			this.update();
		});

		reader.on("noteadded", (note) => {

			this.set(note);
			this.update();
		});

		reader.on("languagechanged", (value) => {

			headerLabel.setValue(strings.get(keys[0]));
			clearBtn.setValue(strings.get(keys[1]));
		});
	}

	set(note) {

		const link = new UILink("#" + note.cfi, note.text);
		const item = new UIItem().setId("note-" + note.uuid);
		const btnr = new UISpan().setClass("btn-remove");
		const call = () => { };

		link.dom.onclick = (e) => {

			if (this.selector && this.selector !== item) {
				this.selector.unselect();
			}
			item.select();
			this.selector = item;
			this.reader.rendition.display(note.cfi);
			e.preventDefault();
		};

		btnr.dom.onclick = (e) => {

			this.removeNote(note);
			e.preventDefault();
		};

		item.add([link, btnr]);
		this.notes.add(item);
		this.reader.rendition.annotations.add(
			"highlight", note.cfi, {}, call, "note-highlight", {});
		this.update();
	}

	removeNote(note) {

		const index = this.reader.settings.annotations.indexOf(note);
		if (index === -1)
			return;

		this.notes.remove(index);
		this.reader.settings.annotations.splice(index, 1);
		this.reader.rendition.annotations.remove(note.cfi, "highlight");
		this.update();
	}

	clearNotes() {

		this.reader.settings.annotations.forEach(note => {
			this.reader.rendition.annotations.remove(note.cfi, "highlight");
		});
		this.notes.clear();
		this.reader.settings.annotations = [];
		this.update();
	}
}