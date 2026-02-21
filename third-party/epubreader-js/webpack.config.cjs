const path = require("path")
const CopyPlugin = require("copy-webpack-plugin")

const config = {
	mode: "development",
	entry: {
		epubreader: "./src/reader.js"
	},
	output: {
		path: path.resolve(__dirname, "dist"),
		libraryTarget: "module"
	},
	externals: {
		"epubjs": "epubjs"
	},
	optimization: {
		usedExports: false
	},
	devServer: {
		static: {
			directory: path.join(__dirname, "dist")
		},
		hot: false,
		liveReload: true,
		compress: true,
		port: 8080
	},
	experiments: {
		outputModule: true
	},
	plugins: [
		new CopyPlugin({
			patterns: [
				{
					from: "node_modules/jszip/dist/jszip.min.js",
					to: "js/libs/jszip.min.js",
					toType: "file",
					force: true
				},
				{
					from: "node_modules/js-md5/build/md5.min.js",
					to: "js/libs/md5.min.js",
					toType: "file",
					force: true
				},
				{
					from: "node_modules/epubjs/dist/epub.min.js",
					to: "js/libs/epub.min.js",
					toType: "file",
					force: true
				},
				{
					from: "assets",
					to: "assets",
					toType: "dir",
					force: true
				},
				{
					from: "index.html",
					to: "index.html",
					toType: "file",
					force: true,
					transform: (content, absoluteFrom) => {
						return content.toString().replace(/dist\//g, "")
					}
				}
			]
		})
	],
	performance: {
		hints: false
	}
}

module.exports = (env, args) => {

	config.devtool = env.WEBPACK_SERVE ? "eval-source-map" : "source-map"

	if (args.optimizationMinimize) {
		config.output.filename = "js/[name].min.js"
		config.output.sourceMapFilename = "js/[name].min.js.map"
		config.optimization.minimize = true
	} else {
		config.output.filename = "js/[name].js"
		config.output.sourceMapFilename = "js/[name].js.map"
		config.optimization.minimize = false
	}

	return config;
}