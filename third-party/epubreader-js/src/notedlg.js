import { uuid } from "./utils.js";
import { UIBox, UIDiv, UIInput, UILabel } from "./ui.js";

export class NoteDlg {

    constructor(reader) {

        const container = new UIDiv().setId("notedlg");
        const strings = reader.strings;
        const keys = [
            "notedlg/label",
            "notedlg/add"
        ];
        const label = new UILabel(strings.get(keys[0]), "note-input");
        const textBox = new UIInput("text", "").setId("note-input");
        textBox.dom.oninput = (e) => {

            this.update();
            e.preventDefault();
        };

        const addBtn = new UIInput("button", strings.get(keys[1]));
        addBtn.dom.disabled = true;
        addBtn.dom.onclick = (e) => {

            const note = {
                cfi: this.cfi,
                date: new Date(),
                text: textBox.getValue(),
                uuid: uuid()
            };
            this.range = undefined;
            reader.settings.annotations.push(note);
            reader.emit("noteadded", note);
            container.removeAttribute("class");
            e.preventDefault();
            addBtn.dom.blur();
        };

        this.update = () => {

            addBtn.dom.disabled = !(this.range && textBox.getValue().length > 0);
        };

        container.add(new UIBox([label, textBox, addBtn]).addClass("control"));
        document.body.appendChild(container.dom);

        //-- events --//

        reader.on("selected", (cfi, contents) => {

            this.cfi = cfi;
            this.range = contents.range(cfi);
            this.update();
            container.setClass("open");

            try {
                const selectedText = this.range.toString().trim();
                const defaultText = selectedText.length > 20 ?
                    selectedText.substring(0, 20) + "..." :
                    selectedText;
                textBox.setValue(defaultText);
            } catch (error) {
                console.warn("Could not get selected text:", error);
                textBox.setValue("");
            }
        });

        reader.on("unselected", () => {

            this.range = undefined;
            this.update();
            container.removeAttribute("class");
        });

        reader.on("languagechanged", (value) => {

            label.setTextContent(strings.get(keys[0]));
            addBtn.setValue(strings.get(keys[1]));
        });
    }
}