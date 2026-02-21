import EventEmitter from "event-emitter";

import { extend, detectMobile } from "./utils.js";
import { Storage } from "./storage.js";
import { Strings } from "./strings.js";
import { Toolbar } from "./toolbar.js";
import { Content } from "./content.js";
import { Sidebar } from "./sidebar.js";
import { NoteDlg } from "./notedlg.js";

export class Reader {

	constructor(bookPath, settings) {

		const preinit = (data) => {
			const url = new URL(window.location);
			let path = bookPath;
			if (settings && !settings.openbook) {
				path = bookPath;
				if (data) this.storage.clear();
			} else if (data && url.search.length === 0) {
				path = data;
			}
			this.cfgInit(path, settings);
			// Apply initial theme to UI
			this.applyUITheme(this.settings.theme);
			this.strings = new Strings(this);
			this.toolbar = new Toolbar(this);
			this.content = new Content(this);
			this.sidebar = new Sidebar(this);
			if (this.settings.annotations) {
				this.notedlg = new NoteDlg(this);
			}
			this.init();
		}

		this.settings = undefined;
		this.isMobile = detectMobile();
		this.storage = new Storage();
		const openbook = settings && settings.openbook;

		if (this.storage.indexedDB && (!settings || openbook)) {
			this.storage.init(() => this.storage.get((data) => preinit(data)));
		} else {
			preinit();
		}

		window.onbeforeunload = this.unload.bind(this);
		window.onhashchange = this.hashChanged.bind(this);
		window.onkeydown = this.keyboardHandler.bind(this);
		window.onwheel = (e) => {
			if (e.ctrlKey) {
				e.preventDefault();
			}
		};
	}

	/**
	 * Initialize book.
	 * @param {*} bookPath
	 * @param {*} settings
	 */
	init(bookPath, settings) {

		this.emit("viewercleanup");
		this.navItems = {};

		if (arguments.length > 0) {

			this.cfgInit(bookPath, settings);
		}

		this.book = ePub(this.settings.bookPath);
		this.rendition = this.book.renderTo("viewer", {
			manager: this.settings.manager,
			flow: this.settings.flow,
			spread: this.settings.spread.mod,
			minSpreadWidth: this.settings.spread.min,
			width: "100%",
			height: "100%",
			snap: true
		});

		const cfi = this.settings.previousLocationCfi;
		if (cfi) {
			this.displayed = this.rendition.display(cfi);
		} else {
			this.displayed = this.rendition.display();
		}

		this.displayed.then((renderer) => {
			this.emit("displayed", renderer, this.settings);
		});

		this.book.ready.then(() => {
			this.emit("bookready", this.settings);
			// Apply styles (theme + font) after book is ready
			this.applyStyles();
		}).then(() => {
			this.emit("bookloaded");
		});

		this.book.loaded.metadata.then((meta) => {
			this.emit("metadata", meta);
		});

		this.book.loaded.navigation.then((toc) => {
			this.emit("navigation", toc);
		});

		this.rendition.on("click", (e) => {
			const selection = e.view.document.getSelection();
			if (selection.type !== "Range") {
				this.emit("unselected");
			}
		});

		this.rendition.on("layout", (props) => {
			this.emit("layout", props);
		});

		this.rendition.on("selected", (cfiRange, contents) => {
			this.setLocation(cfiRange);
			this.emit("selected", cfiRange, contents);
		});

		this.rendition.on("relocated", (location) => {
			this.setLocation(location.start.cfi);
			this.emit("relocated", location);
			// Re-inject font when page changes
			const fontName = this.settings.styles.font === "default" ? "" : this.settings.styles.font;
			if (fontName) {
				setTimeout(() => {
					this.injectFontWithRetry(fontName);
				}, 200);
			}
		});

		this.rendition.on("rendered", () => {
			// Re-inject font when content is rendered
			const fontName = this.settings.styles.font === "default" ? "" : this.settings.styles.font;
			if (fontName) {
				setTimeout(() => {
					this.injectFontWithRetry(fontName);
				}, 100);
			}
		});

		this.rendition.on("keydown", this.keyboardHandler.bind(this));

		this.on("prev", () => {
			if (this.book.package.metadata.direction === "rtl") {
				this.rendition.next();
			} else {
				this.rendition.prev();
			}
		});

		this.on("next", () => {
			if (this.book.package.metadata.direction === "rtl") {
				this.rendition.prev();
			} else {
				this.rendition.next();
			}
		});

		this.on("styleschanged", (value) => {
			if (!value) {
				return;
			}
			if (value.fontSize !== undefined) {
				const fontSize = value.fontSize;
				this.settings.styles.fontSize = fontSize;
				this.rendition.themes.fontSize(fontSize + "%");
			}
			if (value.font !== undefined) {
				let font = value.font;
				if (font === "default") {
					font = "";
				}
				this.settings.styles.font = font;
				// Apply styles with new font
				this.applyStyles();
			}
		});

		this.on("themechanged", (theme) => {
			this.settings.theme = theme;
			// Apply UI theme
			this.applyUITheme(theme);
			// Apply styles with new theme
			this.applyStyles();
		});

		this.on("languagechanged", (language) => {
			this.settings.language = language;
		});

		this.on("flowchanged", (flow) => {
			this.settings.flow = flow;
		});

		this.on("spreadchanged", (spread) => {
			if (spread.mod !== undefined) {
				this.settings.spread.mod = spread.mod;
				// Apply spread mode change to rendition
				this.rendition.spread(spread.mod, this.settings.spread.min);
			}
			if (spread.min !== undefined) {
				this.settings.spread.min = spread.min;
				// Apply minimum spread width change to rendition
				this.rendition.spread(this.settings.spread.mod, spread.min);
			}
		});
	}

	/* ------------------------------- Common ------------------------------- */

	// Helper method to build font URL with configurable assets path
	buildFontUrl(fileName) {
		const baseUrl = window.location.origin + window.location.pathname.replace(/\/[^\/]*$/, '/');
		const assetsPath = this.settings.assetsPath ? this.settings.assetsPath + '/' : '';
		return `${baseUrl}${assetsPath}assets/font/${fileName}`;
	}

	applyUITheme(theme) {
		document.body.className = theme === "dark" ? "dark-theme" :
								  theme === "eyecare" ? "eyecare-theme" : "";
	}

	applyStyles() {
		if (!this.rendition) return;

		const theme = this.settings.theme;
		const fontName = this.settings.styles.font === "default" ? "" : this.settings.styles.font;

		console.log(`Applying styles - Theme: ${theme}, Font: ${fontName || "default"}`);

		// Load font first if needed, then apply styles
		const applyStylesWithFont = (actualFontName) => {
			let contentStyles = {};

			// Helper function to add font-family only if font is specified
			const addFontFamily = (styles, fontName) => {
				if (fontName) {
					styles["font-family"] = fontName + " !important";
				} else {
					styles["font-family"] = "Bookerly !important";
				}
				return styles;
			};

			if (theme === "dark") {
				contentStyles = {
					"body": addFontFamily({
						"background": "#1a1a1a",
						"color": "#e0e0e0 !important"
					}, actualFontName),
					"p": addFontFamily({
						"color": "#e0e0e0 !important"
					}, actualFontName),
					"h1, h2, h3, h4, h5, h6": addFontFamily({
						"color": "#e0e0e0 !important"
					}, actualFontName),
					"div": addFontFamily({}, actualFontName),
					"span": addFontFamily({}, actualFontName),
					"a": addFontFamily({
						"color": "#4a9eff !important"
					}, actualFontName),
					"a:visited": {
						"color": "#b19cd9 !important"
					}
				};
			} else if (theme === "eyecare") {
				contentStyles = {
					"body": addFontFamily({
						"background": "#f0f4e8",
						"color": "#2d4a2d !important"
					}, actualFontName),
					"p": addFontFamily({
						"color": "#2d4a2d !important"
					}, actualFontName),
					"h1, h2, h3, h4, h5, h6": addFontFamily({
						"color": "#2d4a2d !important"
					}, actualFontName),
					"div": addFontFamily({}, actualFontName),
					"span": addFontFamily({}, actualFontName),
					"a": addFontFamily({
						"color": "#4a7c4a !important"
					}, actualFontName),
					"a:visited": {
						"color": "#6b8e6b !important"
					}
				};
			} else {
				// Light theme
				contentStyles = {
					"body": addFontFamily({
						"background": "#fff",
						"color": "#000 !important"
					}, actualFontName),
					"p": addFontFamily({
						"color": "#000 !important"
					}, actualFontName),
					"h1, h2, h3, h4, h5, h6": addFontFamily({
						"color": "#000 !important"
					}, actualFontName),
					"div": addFontFamily({}, actualFontName),
					"span": addFontFamily({}, actualFontName),
					"a": addFontFamily({
						"color": "#1a73e8 !important"
					}, actualFontName),
					"a:visited": {
						"color": "#8e24aa !important"
					}
				};
			}

			this.rendition.themes.default(contentStyles);

			if (actualFontName) {
				this.injectFontWithRetry(actualFontName);
			}

			console.log(`Applied styles with theme: ${theme}, font: ${actualFontName || "default"}`);
		};

		if (fontName) {
			applyStylesWithFont(fontName);
		} else {
			applyStylesWithFont("");
		}
	}

	// Enhanced method to inject font with better timing
	injectFontWithRetry(fontName, maxRetries = 3) {
		if (!fontName || fontName === "default") return;

		let attempts = 0;
		const tryInject = () => {
			attempts++;
			const iframes = document.querySelectorAll('#viewer iframe');

			if (iframes.length === 0 && attempts < maxRetries) {
				console.log(`No iframes found, retrying... (${attempts}/${maxRetries})`);
				setTimeout(tryInject, 200);
				return;
			}

			let injectedCount = 0;
			iframes.forEach(iframe => {
				try {
					const iframeDoc = iframe.contentDocument || iframe.contentWindow.document;
					if (iframeDoc && iframeDoc.readyState === 'complete') {
						// Create or update the font style element
						let fontStyleElement = iframeDoc.getElementById('injected-font-style');
						if (!fontStyleElement) {
							fontStyleElement = iframeDoc.createElement('style');
							fontStyleElement.id = 'injected-font-style';
							iframeDoc.head.appendChild(fontStyleElement);
						}

						const fontFileMapping = {
							"Huiwen-HKHei": "HuiwenGangHei",
							"Huiwen-Fangsong": "HuiwenFangSong",
							"FZSongKeBenXiuKaiS-R-GB": "FangzhengSongJianKe",
							"Bookerly": "Bookerly-Regular"
						};

						const fileName = fontFileMapping[fontName] || fontName;
						const fontUrl = this.buildFontUrl(`${fileName}.ttf`);

						// Inject font-face CSS
						const fontFaceCSS = `
							@font-face {
								font-family: '${fontName}';
								src: url('${fontUrl}') format('truetype');
								font-weight: normal;
								font-style: normal;
							}
						`;

						fontStyleElement.textContent = fontFaceCSS;
						injectedCount++;
						console.log(`Injected font ${fontName} into iframe ${injectedCount}`);
					}
				} catch (error) {
					console.warn(`Failed to inject font into iframe:`, error);
				}
			});

			if (injectedCount === 0 && attempts < maxRetries) {
				console.log(`Font injection failed, retrying... (${attempts}/${maxRetries})`);
				setTimeout(tryInject, 200);
			}
		};

		tryInject();
	}

	navItemFromCfi(cfi) {

		// This feature was added to solve the problem of duplicate titles in
		// bookmarks. But this still has no solution because when reloading the
		// reader, rendition cannot get the range from the previously saved CFI.
		const range = this.rendition.getRange(cfi);
		const idref = range ? range.startContainer.parentNode.id : undefined;
		const location = this.rendition.currentLocation();
		const href = location.start.href;
		return this.navItems[href + "#" + idref] || this.navItems[href];
	}

	/* ------------------------------ Bookmarks ----------------------------- */

	/**
	 * Verifying the current page in bookmarks.
	 * @param {*} cfi
	 * @returns The index of the bookmark if it exists, or -1 otherwise.
	 */
	isBookmarked(cfi) {

		return this.settings.bookmarks.indexOf(cfi);
	}

	/* ----------------------------- Annotations ---------------------------- */

	isAnnotated(note) {

		return this.settings.annotations.indexOf(note);
	}

	/* ------------------------------ Settings ------------------------------ */

	/**
	 * Initialize book settings.
	 * @param {any} bookPath
	 * @param {any} settings
	 */
	cfgInit(bookPath, settings) {

		this.entryKey = md5(bookPath).toString();
		this.settings = {
			bookPath: bookPath,
			assetsPath: "",
			arrows: this.isMobile ? "none" : "content", // none | content | toolbar
			manager: this.isMobile ? "continuous" : "default",
			restore: true,
			history: true,
			openbook: this.storage.indexedDB ? true : false,
			language: "zh",
			theme: "light",
			sectionId: undefined,
			bookmarks: [],   // array | false
			annotations: [], // array | false
			flow: "paginated", // paginated | scrolled
			spread: {
				mod: "auto", // auto | none
				min: 800
			},
			styles: {
				font: "default",
				fontSize: 100
			},
			pagination: undefined, // not implemented
			fullscreen: document.fullscreenEnabled
		};

		extend(settings || {}, this.settings);

		if (this.settings.restore) {
			this.applySavedSettings(settings || {});
		} else {
			this.removeSavedSettings();
		}
	}

	/**
	 * Checks if the book setting can be retrieved from localStorage.
	 * @returns true if the book key exists, or false otherwise.
	 */
	isSaved() {

		return localStorage && localStorage.getItem(this.entryKey) !== null;
	}

	/**
	 * Removing the current book settings from local storage.
	 * @returns true if the book settings were deleted successfully, or false
	 * otherwise.
	 */
	removeSavedSettings() {

		if (!this.isSaved())
			return false;

		localStorage.removeItem(this.entryKey);
		return true;
	}

	/**
	 * Applies saved settings from local storage.
	 * @param {*} external External settings
	 * @returns True if the settings were applied successfully, false otherwise.
	 */
	applySavedSettings(external) {

		if (!this.isSaved())
			return false;

		let stored;
		try {
			stored = JSON.parse(localStorage.getItem(this.entryKey));
		} catch (e) {
			console.exception(e);
		}

		if (stored) {
			extend(stored, this.settings, external);
			return true;
		} else {
			return false;
		}
	}

	/**
	 * Saving the current book settings in local storage.
	 */
	saveSettings() {

		this.settings.previousLocationCfi = this.rendition.location.start.cfi;
		const cfg = Object.assign({}, this.settings);
		delete cfg.arrows;
		delete cfg.manager;
		delete cfg.history;
		delete cfg.restore;
		delete cfg.openbook;
		delete cfg.pagination;
		delete cfg.fullscreen;
		localStorage.setItem(this.entryKey, JSON.stringify(cfg));
	}

	setLocation(cfi) {

		const baseUrl = this.book.archived ? undefined : this.book.url;
		const url = new URL(window.location, baseUrl);
		url.hash = "#" + cfi;

		// Update the History Location
		if (this.settings.history && window.location.hash !== url.hash) {
			// Add CFI fragment to the history
			window.history.pushState({}, "", url);
			this.currentLocationCfi = cfi;
		}
	}

	//-- event handlers --//

	unload() {

		if (this.settings.restore && localStorage) {
			this.saveSettings();
		}
	}

	hashChanged() {

		const hash = window.location.hash.slice(1);
		this.rendition.display(hash);
	}

	keyboardHandler(e) {

		const step = 2;
		let value = this.settings.styles.fontSize;

		switch (e.key) {

			case "=":
			case "+":
				value += step;
				this.emit("styleschanged", { fontSize: value });
				break;
			case "-":
				value -= step;
				this.emit("styleschanged", { fontSize: value });
				break;
			case "0":
				value = 100;
				this.emit("styleschanged", { fontSize: value });
				break;
			case "ArrowLeft":
				this.emit("prev");
				break;
			case "ArrowRight":
				this.emit("next");
				break;
		}
	}
}

EventEmitter(Reader.prototype);