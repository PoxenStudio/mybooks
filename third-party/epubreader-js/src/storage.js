export class Storage {

	constructor() {

		this.name = "epubreader-js";
		this.version = 1.0;
		this.db;
		this.indexedDB = window.indexedDB ||
			window.webkitIndexedDB ||
			window.mozIndexedDB ||
			window.OIndexedDB ||
			window.msIndexedDB;

		if (this.indexedDB === undefined) {

			console.error("The IndexedDB API not available in your browser.");
		}
	}

	init(callback) {

		if (this.indexedDB === undefined) {
			callback();
			return;
		}

		const time = Date.now();
		const onerror = (e) => console.error("IndexedDB", e);
		const request = indexedDB.open(this.name, this.version);
		request.onupgradeneeded = (e) => {

			const db = e.target.result;
			if (db.objectStoreNames.contains("entries") === false) {
				db.createObjectStore("entries");
			}
		}

		request.onsuccess = (e) => {

			this.db = e.target.result;
			this.db.onerror = onerror;
			callback();
			console.log(`storage.init: ${Date.now() - time} ms`);
		}

		request.onerror = onerror;
	}

	get(callback) {

		if (this.db === undefined) {
			callback();
			return;
		}

		const time = Date.now();
		const transaction = this.db.transaction(["entries"], "readwrite");
		const objectStore = transaction.objectStore("entries");
		const request = objectStore.get(0);
		request.onsuccess = (e) => {

			callback(e.target.result);
			console.log(`storage.get: ${Date.now() - time} ms`);
		}
	}

	set(data, callback) {

		if (this.db === undefined) {
			callback();
			return;
		}

		const time = Date.now();
		const transaction = this.db.transaction(["entries"], "readwrite");
		const objectStore = transaction.objectStore("entries");
		const request = objectStore.put(data, 0);
		request.onsuccess = () => {

			callback();
			console.log(`storage.set: ${Date.now() - time} ms`);
		}
	}

	clear() {

		if (this.db === undefined) {
			return;
		}

		const time = Date.now();
		const transaction = this.db.transaction(["entries"], "readwrite");
		const objectStore = transaction.objectStore("entries");
		const request = objectStore.clear();
		request.onsuccess = () => {

			console.log(`storage.clear: ${Date.now() - time} ms`);
		}
	}
}