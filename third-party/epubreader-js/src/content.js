import { UIDiv, UISpan } from "./ui.js";

export class Content {

	constructor(reader) {

		const settings = reader.settings;
		const container = new UIDiv().setId("content");

		let prev;
		if (settings.arrows === "content") {

			prev = new UIDiv().setId("prev").setClass("arrow");
			prev.dom.onclick = (e) => {

				reader.emit("prev");
				e.preventDefault();
			};
			prev.add(new UISpan("<"));
			container.add(prev);
		}

		const viewer = new UIDiv().setId("viewer");
		container.add(viewer);

		let next;
		if (settings.arrows === "content") {
			next = new UIDiv().setId("next").setClass("arrow");
			next.dom.onclick = (e) => {

				reader.emit("next");
				e.preventDefault();
			};
			next.add(new UISpan(">"));
			container.add(next);
		}

		const loader = new UIDiv().setId("loader");
		const divider = new UIDiv().setId("divider");
		const overlay = new UIDiv().setId("overlay");
		overlay.dom.onclick = (e) => {
			reader.emit("sidebaropener", false);
			e.preventDefault();
		};

		container.add([loader, divider, overlay]);
		document.body.appendChild(container.dom);

		//-- events --//

		reader.on("bookready", (cfg) => {

			viewer.setClass(cfg.flow);
			loader.dom.style.display = "block";
		});

		reader.on("bookloaded", () => {

			loader.dom.style.display = "none";
		});

		reader.on("layout", (props) => {

			if (props.spread && props.width > props.spreadWidth) {
				divider.dom.style.display = "block";
			} else {
				divider.dom.style.display = "none";
			}
		});

		reader.on("flowchanged", (value) => {
			
			viewer.setClass(value);
		});

		reader.on("relocated", (location) => {

			if (settings.arrows === "content") {
				if (location.atStart) {
					prev.addClass("disabled");
				} else {
					prev.removeClass("disabled");
				}
				if (location.atEnd) {
					next.addClass("disabled");
				} else {
					next.removeClass("disabled");
				}
			}
		});

		reader.on("prev", () => {

			if (settings.arrows === "content") {
				prev.addClass("active");
				setTimeout(() => { prev.removeClass("active"); }, 100);
			}
		});

		reader.on("next", () => {

			if (settings.arrows === "content") {
				next.addClass("active");
				setTimeout(() => { next.removeClass("active"); }, 100);
			}
		});

		reader.on("sidebaropener", (value) => {

			overlay.dom.style.display = value ? "block" : "none";
		});

		reader.on("viewercleanup", () => {

			viewer.clear();
		});
	}
}