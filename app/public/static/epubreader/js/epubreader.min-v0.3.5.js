/*! epubreader-js v0.3.5 */
/******/var e={
/***/11:
/***/e=>{
// eslint-disable-next-line no-empty-function
e.exports=function(){};
/***/},
/***/68:
/***/(e,t,s)=>{var n,o,i,a,r,d,l,c=s(263),h=s(499),m=Function.prototype.apply,u=Function.prototype.call,g=Object.create,b=Object.defineProperty,p=Object.defineProperties,f=Object.prototype.hasOwnProperty,w={configurable:!0,enumerable:!1,writable:!0};o=function(e,t){var s,o;return h(t),o=this,n.call(this,e,s=function(){i.call(o,e,s),m.call(t,this,arguments)}),s.__eeOnceListener__=t,this},r={on:n=function(e,t){var s;return h(t),f.call(this,"__ee__")?s=this.__ee__:(s=w.value=g(null),b(this,"__ee__",w),w.value=null),s[e]?"object"==typeof s[e]?s[e].push(t):s[e]=[s[e],t]:s[e]=t,this},once:o,off:i=function(e,t){var s,n,o,i;if(h(t),!f.call(this,"__ee__"))return this;if(!(s=this.__ee__)[e])return this;if("object"==typeof(n=s[e]))for(i=0;o=n[i];++i)o!==t&&o.__eeOnceListener__!==t||(2===n.length?s[e]=n[i?0:1]:n.splice(i,1));else n!==t&&n.__eeOnceListener__!==t||delete s[e];return this},emit:a=function(e){var t,s,n,o,i;if(f.call(this,"__ee__")&&(o=this.__ee__[e]))if("object"==typeof o){for(s=arguments.length,i=new Array(s-1),t=1;t<s;++t)i[t-1]=arguments[t];for(o=o.slice(),t=0;n=o[t];++t)m.call(n,this,i)}else switch(arguments.length){case 1:u.call(o,this);break;case 2:u.call(o,this,arguments[1]);break;case 3:u.call(o,this,arguments[1],arguments[2]);break;default:for(s=arguments.length,i=new Array(s-1),t=1;t<s;++t)i[t-1]=arguments[t];m.call(o,this,i)}}},d={on:c(n),once:c(o),off:c(i),emit:c(a)},l=p({},d),e.exports=t=function(e){return null==e?g(l):p(Object(e),d)},t.methods=r},
/***/80:
/***/(e,t,s)=>{var n=s(202);e.exports=function(e){if("function"!=typeof e)return!1;if(!hasOwnProperty.call(e,"length"))return!1;try{if("number"!=typeof e.length)return!1;if("function"!=typeof e.call)return!1;if("function"!=typeof e.apply)return!1}catch(e){return!1}return!n(e)}},
/***/93:
/***/(e,t,s)=>{e.exports=s(380)()?Object.keys:s(232);
/***/},
/***/134:
/***/(e,t,s)=>{var n=s(762);e.exports=function(e){if(!n(e))throw new TypeError("Cannot use null or undefined");return e}},
/***/148:
/***/(e,t,s)=>{var n=s(762),o=Array.prototype.forEach,i=Object.create;
// eslint-disable-next-line no-unused-vars
e.exports=function(e/*, …options*/){var t=i(null);return o.call(arguments,(function(e){n(e)&&function(e,t){var s;for(s in e)t[s]=e[s]}(Object(e),t)})),t}},
/***/175:
/***/e=>{e.exports=function(e){return null!=e}},
/***/181:
/***/(e,t,s)=>{var n=s(175),o={object:!0,function:!0,undefined:!0/* document.all */};
// prettier-ignore
e.exports=function(e){return!!n(e)&&hasOwnProperty.call(o,typeof e)}},
/***/202:
/***/(e,t,s)=>{var n=s(181);e.exports=function(e){if(!n(e))return!1;try{return!!e.constructor&&e.constructor.prototype===e}catch(e){return!1}}},
/***/214:
/***/(e,t,s)=>{e.exports=s(525)()?String.prototype.contains:s(521);
/***/},
/***/232:
/***/(e,t,s)=>{var n=s(762),o=Object.keys;e.exports=function(e){return o(n(e)?Object(e):e)}},
/***/263:
/***/(e,t,s)=>{var n=s(175),o=s(873),i=s(596),a=s(148),r=s(214);(e.exports=function(e,t/*, options*/){var s,o,d,l,c;return arguments.length<2||"string"!=typeof e?(l=t,t=e,e=null):l=arguments[2],n(e)?(s=r.call(e,"c"),o=r.call(e,"e"),d=r.call(e,"w")):(s=d=!0,o=!1),c={value:t,configurable:s,enumerable:o,writable:d},l?i(a(l),c):c}).gs=function(e,t,s/*, options*/){var d,l,c,h;return"string"!=typeof e?(c=s,s=t,t=e,e=null):c=arguments[3],n(t)?o(t)?n(s)?o(s)||(c=s,s=void 0):s=void 0:(c=t,t=s=void 0):t=void 0,n(e)?(d=r.call(e,"c"),l=r.call(e,"e")):(d=!0,l=!1),h={get:t,set:s,configurable:d,enumerable:l},c?i(a(c),h):h}},
/***/339:
/***/e=>{e.exports=function(){var e,t=Object.assign;return"function"==typeof t&&(t(e={foo:"raz"},{bar:"dwa"},{trzy:"trzy"}),e.foo+e.bar+e.trzy==="razdwatrzy")};
/***/},
/***/380:
/***/e=>{e.exports=function(){try{return Object.keys("primitive"),!0}catch(e){return!1}};
/***/},
/***/499:
/***/e=>{e.exports=function(e){if("function"!=typeof e)throw new TypeError(e+" is not a function");return e};
/***/},
/***/521:
/***/e=>{var t=String.prototype.indexOf;e.exports=function(e/*, position*/){return t.call(this,e,arguments[1])>-1}},
/***/525:
/***/e=>{var t="razdwatrzy";e.exports=function(){return"function"==typeof t.contains&&(!0===t.contains("dwa")&&!1===t.contains("foo"))}},
/***/595:
/***/(e,t,s)=>{var n=s(93),o=s(134),i=Math.max;e.exports=function(e,t/*, …srcn*/){var s,a,r,d=i(arguments.length,2);for(e=Object(o(e)),r=function(n){try{e[n]=t[n]}catch(e){s||(s=e)}},a=1;a<d;++a)n(t=arguments[a]).forEach(r);if(void 0!==s)throw s;return e}},
/***/596:
/***/(e,t,s)=>{e.exports=s(339)()?Object.assign:s(595);
/***/},
/***/762:
/***/(e,t,s)=>{var n=s(11)();// Support ES3 engines
e.exports=function(e){return e!==n&&null!==e}},
/***/873:
/***/(e,t,s)=>{var n=s(80),o=/^\s*class[\s{/}]/,i=Function.prototype.toString;e.exports=function(e){return!!n(e)&&!o.test(i.call(e))}}
/******/},t={};
/************************************************************************/
/******/ // The module cache
/******/
// EXTERNAL MODULE: ./node_modules/event-emitter/index.js
var s=
/******/
/******/ // The require function
/******/function s(n){
/******/ // Check if module is in cache
/******/var o=t[n];
/******/if(void 0!==o)
/******/return o.exports;
/******/
/******/ // Create a new module (and put it into the cache)
/******/var i=t[n]={
/******/ // no module.id needed
/******/ // no module.loaded needed
/******/exports:{}
/******/};
/******/
/******/ // Execute the module function
/******/
/******/
/******/ // Return the exports of the module
/******/return e[n](i,i.exports,s),i.exports;
/******/}
/******/
/************************************************************************/(68);// ./src/utils.js
const n=(e,t)=>e?e[t]:void 0,o=(e,t,s,o)=>{let i;if("boolean"==typeof t[o])switch(o){case"annotations":case"bookmarks":i=t[o]?e[o]:t[o];break;default:i=t[o]}else i="arrows"===o?t[o]:void 0===n(s,o)?e[o]:t[o];return i},i=(e,t,s)=>{for(let a in e)"bookPath"!==a&&(t[a]instanceof Array?t[a]=s?e[a]?e[a]:t[a]:e[a]:t[a]instanceof Object?i(e[a],t[a],n(s,a)):t[a]=s?o(e,t,s,a):e[a])},a=()=>{let e=(new Date).getTime();return"xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g,(t=>{let s=(e+16*Math.random())%16|0;return e=Math.floor(e/16),("x"===t?s:7&s|8).toString(16)}))},r=()=>[/Android/i,/BlackBerry/i,/iPhone/i,/iPad/i,/iPod/i,/Windows Phone/i,/webOS/i].some((e=>navigator.userAgent.match(e)));// ./src/storage.js
class d{constructor(){this.name="epubreader-js",this.version=1,this.db,this.indexedDB=window.indexedDB||window.webkitIndexedDB||window.mozIndexedDB||window.OIndexedDB||window.msIndexedDB,void 0===this.indexedDB&&console.error("The IndexedDB API not available in your browser.")}init(e){if(void 0===this.indexedDB)return void e();const t=Date.now(),s=e=>console.error("IndexedDB",e),n=indexedDB.open(this.name,this.version);n.onupgradeneeded=e=>{const t=e.target.result;!1===t.objectStoreNames.contains("entries")&&t.createObjectStore("entries")},n.onsuccess=n=>{this.db=n.target.result,this.db.onerror=s,e(),console.log(`storage.init: ${Date.now()-t} ms`)},n.onerror=s}get(e){if(void 0===this.db)return void e();const t=Date.now();this.db.transaction(["entries"],"readwrite").objectStore("entries").get(0).onsuccess=s=>{e(s.target.result),console.log(`storage.get: ${Date.now()-t} ms`)}}set(e,t){if(void 0===this.db)return void t();const s=Date.now();this.db.transaction(["entries"],"readwrite").objectStore("entries").put(e,0).onsuccess=()=>{t(),console.log(`storage.set: ${Date.now()-s} ms`)}}clear(){if(void 0===this.db)return;const e=Date.now();this.db.transaction(["entries"],"readwrite").objectStore("entries").clear().onsuccess=()=>{console.log(`storage.clear: ${Date.now()-e} ms`)}}}// ./src/strings.js
class l{constructor(e){this.language=e.settings.language||"en",this.values={en:{"toolbar/sidebar":"Sidebar","toolbar/prev":"Previous page","toolbar/next":"Next page","toolbar/openbook":"Open book","toolbar/openbook/error":"Your browser does not support the required features.\nPlease use a modern browser such as Google Chrome, or Mozilla Firefox.","toolbar/bookmark":"Add this page to bookmarks","toolbar/fullscreen":"Fullscreen","sidebar/close":"Close Sidebar","sidebar/contents":"Contents","sidebar/bookmarks":"Bookmarks","sidebar/bookmarks/add":"Add","sidebar/bookmarks/remove":"Remove","sidebar/bookmarks/clear":"Clear","sidebar/annotations":"Annotations","sidebar/annotations/add":"Add","sidebar/annotations/remove":"Remove","sidebar/annotations/clear":"Clear","sidebar/annotations/anchor":"Anchor","sidebar/annotations/cancel":"Cancel","sidebar/search":"Search","sidebar/search/placeholder":"Search","sidebar/settings":"Settings","sidebar/settings/language":"Language","sidebar/settings/font":"Font","sidebar/settings/font/default":"Default","sidebar/settings/fontsize":"Font size (%)","sidebar/settings/flow":"Flow","sidebar/settings/pagination":["Pagination","Generate pagination"],"sidebar/settings/spread":"Spread","sidebar/settings/spread/items":["None","Auto"],"sidebar/settings/spread/minwidth":"Minimum spread width","sidebar/settings/theme":"Theme","sidebar/settings/theme/items":["Light","Dark","Eye Care"],"sidebar/metadata":"Metadata","sidebar/metadata/title":"Title","sidebar/metadata/creator":"Creator","sidebar/metadata/description":"Description","sidebar/metadata/pubdate":"Pubdate","sidebar/metadata/publisher":"Publisher","sidebar/metadata/identifier":"Identifier","sidebar/metadata/language":"Language","sidebar/metadata/rights":"Rights","sidebar/metadata/modified_date":"Modified date","sidebar/metadata/layout":"Layout",// rendition:layout
"sidebar/metadata/flow":"Flow",// rendition:flow
"sidebar/metadata/spread":"Spread",// rendition:spread
"sidebar/metadata/direction":"Direction",// page-progression-direction
"notedlg/label":"Note","notedlg/add":"Add"},zh:{"toolbar/sidebar":"侧边栏","toolbar/prev":"上一页","toolbar/next":"下一页","toolbar/openbook":"打开书籍","toolbar/openbook/error":"您的浏览器不支持所需功能。\n请使用现代浏览器如谷歌Chrome或火狐Firefox。","toolbar/bookmark":"加为书签","toolbar/fullscreen":"全屏","sidebar/close":"关闭侧边栏","sidebar/contents":"目录","sidebar/bookmarks":"书签","sidebar/bookmarks/add":"添加","sidebar/bookmarks/remove":"移除","sidebar/bookmarks/clear":"清空","sidebar/annotations":"注解","sidebar/annotations/add":"添加","sidebar/annotations/remove":"移除","sidebar/annotations/clear":"清空","sidebar/annotations/anchor":"锚定","sidebar/annotations/cancel":"取消","sidebar/search":"搜索","sidebar/search/placeholder":"搜索","sidebar/settings":"设置","sidebar/settings/language":"语言","sidebar/settings/font":"字体","sidebar/settings/font/default":"默认字体","sidebar/settings/fontsize":"字体大小 (%)","sidebar/settings/flow":"换页",// Scrolled = "滚动模式"
"sidebar/settings/pagination":["分页模式","滚动模式"],"sidebar/settings/spread":"双页布局","sidebar/settings/spread/items":["无","自动"],"sidebar/settings/spread/minwidth":"最小双页宽度","sidebar/settings/theme":"颜色主题","sidebar/settings/theme/items":["亮色","暗色","护眼"],"sidebar/metadata":"元数据","sidebar/metadata/title":"标题","sidebar/metadata/creator":"作者","sidebar/metadata/description":"描述","sidebar/metadata/pubdate":"出版日期","sidebar/metadata/publisher":"出版商","sidebar/metadata/identifier":"标识符","sidebar/metadata/language":"语言","sidebar/metadata/rights":"版权","sidebar/metadata/modified_date":"修改日期","sidebar/metadata/layout":"布局",// rendition:layout
"sidebar/metadata/flow":"流模式",// rendition:flow
"sidebar/metadata/spread":"双页布局",// rendition:spread
"sidebar/metadata/direction":"阅读方向",// page-progression-direction
"notedlg/label":"笔记","notedlg/add":"添加"}},e.on("languagechanged",(e=>{this.language=e}))}get(e){return this.values[this.language][e]||"???"}}// ./src/ui.js
/**
 * @author mrdoob https://github.com/mrdoob/ui.js
 */
const c="is not an instance of UIElement.";
/**
 * UIElement
 * @param {string} tag
 */class h{constructor(e){this.dom=document.createElement(e)}add(){for(let e=0;e<arguments.length;e++){const t=arguments[e];if(t instanceof h)this.dom.appendChild(t.dom);else if(Array.isArray(t))for(let e=0;e<t.length;e++){const s=t[e];s instanceof h?this.dom.appendChild(s.dom):console.error("UIElement:",s,c)}else console.error("UIElement:",t,c)}return this}remove(){for(let e=0;e<arguments.length;e++){const t=arguments[e];t instanceof h?this.dom.removeChild(t.dom):Number.isInteger(t)?this.dom.removeChild(this.dom.childNodes[t]):console.error("UIElement:",t,c)}return this}clear(){for(;this.dom.children.length;)this.dom.removeChild(this.dom.lastChild);return this}setId(e){return this.dom.id=e,this}getId(){return this.dom.id}removeAttribute(e){return this.dom.removeAttribute(e),this}setClass(e){return this.dom.className=e,this}addClass(e){return this.dom.classList.add(e),this}removeClass(e){return this.dom.classList.remove(e),this}setStyle(e,t){return this.dom.style[e]=t,this}getTitle(){return this.dom.title}setTitle(e){return this.dom.title!==e&&e&&(this.dom.title=e),this}getTextContent(){return this.dom.textContent}setTextContent(e){return this.dom.textContent!==e&&e&&(this.dom.textContent=e),this}getBoundingClientRect(){return this.dom.getBoundingClientRect()}}
/**
 * UISpan
 * @param {string} text
 */class m extends h{constructor(e){super("span"),this.setTextContent(e)}}
/**
 * UIDiv
 */class u extends h{constructor(){super("div")}}
/**
 * UIRow
 */class g extends u{constructor(){super(),this.dom.className="row"}}
/**
 * UIPanel
 */class b extends u{constructor(){super(),this.dom.className="panel"}}
/**
 * UILabel
 * @param {string} text
 * @param {string} id
 */class p extends h{constructor(e,t){super("label"),this.dom.textContent=e,t&&(this.dom.htmlFor=t)}}
/**
 * UILink
 * @param {string} href
 * @param {string} text
 */class f extends h{constructor(e,t){super("a"),this.dom.href=e||"#",this.dom.textContent=t||""}setHref(e){return this.dom.href=e,this}}
/**
 * UIText
 * @param {string} text
 */class w extends m{constructor(e){super(),this.dom.textContent=e}getValue(){return this.dom.textContent}setValue(e){return this.dom.textContent=e,this}}
/**
 * UITextArea
 */
/**
 * UISelect
 */
class v extends h{constructor(){super("select")}setMultiple(e){return this.dom.multiple=e||!1,this}setOptions(e){const t=this.dom.value;this.clear();for(const t in e){const s=document.createElement("option");s.value=t,s.text=e[t],this.dom.appendChild(s)}return this.dom.value=t,this}getValue(){return this.dom.value}setValue(e){return e=String(e),this.dom.value!==e&&(this.dom.value=e),this}}
/**
 * UIInput
 * @param {*} type
 * @param {*} value
 * @param {*} title
 */class k extends h{constructor(e,t,s){super("input"),this.dom.type=e,this.dom.onkeydown=e=>{e.stopPropagation()},this.setValue(t),this.setTitle(s)}getName(){return this.dom.name}setName(e){return this.dom.name=e,this}getType(){return this.dom.type}setType(e){return this.dom.type=e,this}getValue(){return this.dom.value}setValue(e){return this.dom.value!==e&&void 0!==e&&(this.dom.value=e),this}}
/**
 * UIColor
 */
/**
 * UINumber
 * @param {number} value
 * @param {number} step
 * @param {number} min
 * @param {number} max
 * @param {number} precision
 */
class y extends h{constructor(e,t,s,n,o){super("input"),this.dom.type="number",this.dom.step=t||1,this.dom.onkeydown=e=>{e.stopPropagation()},this.value=e||0,this.min=s||-1/0,this.max=n||1/0,this.precision=o||0,this.setValue(e),this.dom.onchange=e=>{this.setValue(this.value)}}getName(){return this.dom.name}setName(e){return this.dom.name=e,this}setPrecision(e){return this.precision=e,this.setValue(this.value),this}setRange(e,t){return this.min=e,this.max=t,this.dom.min=e,this.dom.max=t,this}setStep(e){return this.dom.step=e,this}getValue(){return parseFloat(this.dom.value)}setValue(e){return void 0!==e&&((e=parseFloat(e))<this.min&&(e=this.min),e>this.max&&(e=this.max),this.value=e,this.dom.value=e.toFixed(this.precision)),this}}
/**
 * UIBreak
 */
/**
 * UITabbedPanel
 * @param {string} align (horizontal | vertical)
 */
class x extends u{constructor(e){super(),this.align=e||"horizontal",this.tabs=[],this.panels=[],this.selector=(new m).setClass("tab-selector"),this.menuDiv=(new u).setClass("menu"),this.tabsDiv=(new u).setClass("tabs"),this.tabsDiv.add(this.selector),this.panelsDiv=(new u).setClass("panels"),this.selected="",this.add(this.menuDiv),this.add(this.tabsDiv),this.add(this.panelsDiv)}addMenu(e){this.menuDiv.add(e)}addTab(e,t,s){const n=new C(t,this);n.setId(e),n.setClass("box"),this.tabs.push(n),this.tabsDiv.add(n);const o=new u;o.setId(e),o.add(s),this.panels.push(o),this.panelsDiv.add(o),this.select(e)}select(e){for(let t of this.tabs)t.dom.id===e?(t.addClass("selected"),this.transformSelector(t)):t.dom.id===this.selected&&t.removeClass("selected");for(let t of this.panels)t.dom.id===e?t.dom.style.display="block":t.dom.id===this.selected&&(t.dom.style.display="none");return this.selected=e,this}setLabel(e,t){for(let s of this.tabs)if(s.dom.id===e){s.setTitle(t);break}}transformSelector(e){let t;const s=e.getBoundingClientRect();"horizontal"===this.align?(t=s.width*this.tabs.indexOf(e),this.selector.dom.style.transform=`translateX(${t}px)`):(t=s.height*this.tabs.indexOf(e),this.selector.dom.style.transform=`translateY(${t}px)`)}}
/**
 * UITab
 * @param {string} text
 * @param {UITabbedPanel} parent
 */class C extends u{constructor(e,t){super(),this.button=new k("button"),this.button.dom.title=e,this.dom.onclick=e=>{t.select(this.dom.id),e.preventDefault()},this.add(this.button)}}
/**
 * UIList
 * @param {UIItem} parent
 */class S extends h{constructor(e){super("ul"),this.parent=e&&e.parent,// LI->UL
this.expanded=!1}expand(){return this.expanded=!0,this.dom.style.display="block",this.parent&&this.parent.expand(),this}collaps(){return this.expanded=!1,this.dom.style.display="none",this}}
/**
 * UIItem
 * @param {UIList} parent
 */class I extends h{constructor(e){super("li"),this.parent=e,// UL
this.selected=!1}add(){let e=0;const t=(new u).setId("item-box");for(let s=0;s<arguments.length;s++){const n=arguments[s];n instanceof S?super.add(n):(t.add(n),e++)}return e&&super.add(t),this}select(){return this.selected=!0,this.setClass("selected"),this}unselect(){return this.selected=!1,this.removeAttribute("class"),this}}
/**
 * UIBox
 * @param {UIElement} items
 */class D extends h{constructor(e){super("div"),this.setClass("box"),this.add(e)}}// ./src/toolbar.js
class T{constructor(e){const t=e.strings,s=e.settings;this.isMobile=r();const n=(new u).setId("toolbar"),o=["toolbar/sidebar","toolbar/prev","toolbar/next","toolbar/openbook","toolbar/openbook/error","toolbar/bookmark","toolbar/fullscreen","toolbar/close"],i=(new u).setClass("menu-1"),a=(new u).setId("btn-m").setClass("box"),d=new k("button");let l,c,h,m;d.dom.title=t.get(o[0]),d.dom.onclick=t=>{e.emit("sidebaropener",!0),d.dom.blur(),t.preventDefault()},a.add(d),i.add(a),"toolbar"===s.arrows&&(l=(new u).setId("btn-p").setClass("box"),c=new k("button"),c.setTitle(t.get(o[1])),c.dom.onclick=t=>{e.emit("prev"),t.preventDefault(),c.dom.blur()},l.add(c),i.add(l),h=(new u).setId("btn-n").setClass("box"),m=new k("button"),m.dom.title=t.get(o[2]),m.dom.onclick=t=>{e.emit("next"),t.preventDefault(),m.dom.blur()},h.add(m),i.add(h));const g=(new u).setClass("menu-2");let b,p,f,w;if(s.openbook){const s=t=>{e.storage.clear(),e.storage.set(t.target.result,(()=>{e.unload(),e.init(t.target.result);const s=new URL(window.location.origin);window.history.replaceState({},"",s)}))},n=e=>{console.error(e)},i=(new u).setId("btn-o").setClass("box");b=new k("file"),b.dom.title=t.get(o[3]),b.dom.accept="application/epub+zip",b.dom.onchange=e=>{if(0!==e.target.files.length)if(window.FileReader){const t=new FileReader;t.onload=s,t.readAsArrayBuffer(e.target.files[0]),t.onerror=n}else alert(t.get(o[4]))},b.dom.onclick=e=>{b.dom.blur()},i.add(b),g.add(i)}if(s.bookmarks&&(p=(new u).setId("btn-b").setClass("box"),f=new k("button"),f.setTitle(t.get(o[6])),f.dom.onclick=t=>{const s=this.locationCfi,n=-1===e.isBookmarked(s);e.emit("bookmarked",n),t.preventDefault(),f.dom.blur()},p.add(f),g.add(p)),s.fullscreen){const e=(new u).setId("btn-f").setClass("box");w=new k("button"),w.setTitle(t.get(o[6])),w.dom.onclick=e=>{this.toggleFullScreen(),e.preventDefault()},document.onkeydown=e=>{"F11"===e.key&&(e.preventDefault(),this.toggleFullScreen())},document.onfullscreenchange=t=>{const s=window.screen.width===t.target.clientWidth,n=window.screen.height===t.target.clientHeight;s&&n?e.addClass("resize-small"):e.removeClass("resize-small")},e.add(w),g.add(e)}if(this.isMobile){let e,s;console.log("Mobile device detected, hiding spread and pagination options."),e=(new u).setId("btn-e").setClass("box"),s=new k("button"),s.setTitle(t.get(o[7])),s.dom.onclick=e=>{
// Close the reader on mobile devices
window.history.back(),e.preventDefault(),s.dom.blur()},e.add(s),g.add(e)}const v=(new u).setClass("menu-center"),y=(new u).setClass("chapter-title");v.add(y),n.add([i,v,g]),document.body.appendChild(n.dom),
//-- events --//
e.on("chapterChanged",(e=>{y.dom.textContent=e})),e.on("relocated",(t=>{if(s.bookmarks){const s=t.start.cfi;-1===e.isBookmarked(s)?p.removeClass("bookmarked"):p.addClass("bookmarked"),this.locationCfi=s}"toolbar"===s.arrows&&(l.dom.style.display=t.atStart?"none":"block",h.dom.style.display=t.atEnd?"none":"block")})),e.on("bookmarked",(e=>{e?p.addClass("bookmarked"):p.removeClass("bookmarked")})),e.on("languagechanged",(e=>{d.setTitle(t.get(o[0])),"toolbar"===s.arrows&&(c.setTitle(t.get(o[1])),m.setTitle(t.get(o[2]))),s.openbook&&b.setTitle(t.get(o[3])),s.bookmarks&&f.setTitle(t.get(o[5])),s.fullscreen&&w.setTitle(t.get(o[6]))}))}toggleFullScreen(){document.activeElement.blur(),null===document.fullscreenElement?document.documentElement.requestFullscreen():document.exitFullscreen&&document.exitFullscreen()}}// ./src/content.js
class B{constructor(e){const t=e.settings,s=(new u).setId("content");let n;"content"===t.arrows&&(n=(new u).setId("prev").setClass("arrow"),n.dom.onclick=t=>{e.emit("prev"),t.preventDefault()},n.add(new m("<")),s.add(n));const o=(new u).setId("viewer");let i;s.add(o),"content"===t.arrows&&(i=(new u).setId("next").setClass("arrow"),i.dom.onclick=t=>{e.emit("next"),t.preventDefault()},i.add(new m(">")),s.add(i));const a=(new u).setId("loader"),r=(new u).setId("divider"),d=(new u).setId("overlay");d.dom.onclick=t=>{e.emit("sidebaropener",!1),t.preventDefault()},s.add([a,r,d]),document.body.appendChild(s.dom),o.setClass(t.flow),
//-- events --//
e.on("bookready",(e=>{console.log("[Content] book is ready"),o.setClass(e.flow),a.dom.style.display="block"})),e.on("bookloaded",(()=>{console.log("[Content] book is loaded"),a.dom.style.display="none"})),e.on("layout",(e=>{console.log("[Content] try to layout"),e.spread&&e.width>e.spreadWidth?r.dom.style.display="block":r.dom.style.display="none"})),e.on("flowchanged",(e=>{o.setClass(e)})),e.on("relocated",(e=>{"content"===t.arrows&&(e.atStart?n.addClass("disabled"):n.removeClass("disabled"),e.atEnd?i.addClass("disabled"):i.removeClass("disabled"))})),e.on("prev",(()=>{"content"===t.arrows&&(n.addClass("active"),setTimeout((()=>{n.removeClass("active")}),100))})),e.on("next",(()=>{"content"===t.arrows&&(i.addClass("active"),setTimeout((()=>{i.removeClass("active")}),100))})),e.on("sidebaropener",(e=>{d.dom.style.display=e?"block":"none"})),e.on("viewercleanup",(()=>{o.clear()}))}}// ./src/sidebar/toc.js
class O extends b{constructor(e){super();const t=(new u).setClass("list-container"),s=e.strings,n=["sidebar/contents"],o=new w(s.get(n[0])).setClass("label");this.reader=e,this.selector=void 0,// save reference to selected tree item
this.setId("contents"),this.add(new D(o).addClass("header")),
//-- events --//
e.on("navigation",(e=>{t.clear(),t.add(this.generateToc(e)),this.add(t)})),e.on("languagechanged",(e=>{o.setValue(s.get(n[0]))}))}generateToc(e,t){const s=new S(t);return e.forEach((e=>{const t=new f(e.href,e.label),n=new I(s).setId(e.id),o=new m;if(t.dom.onclick=t=>{this.selector&&this.selector!==n&&this.selector.unselect(),n.select(),this.selector=n,this.reader.settings.sectionId=e.id,this.reader.rendition.display(e.href),t.preventDefault()},n.add([o,t]),this.reader.navItems[e.href]={id:e.id,label:e.label},this.reader.settings.sectionId===e.id&&(s.expand(),n.select(),this.selector=n),e.subitems&&e.subitems.length>0){const t=this.generateToc(e.subitems,n);o.setClass("toggle-collapsed"),o.dom.onclick=()=>(t.expanded?(t.collaps(),o.setClass("toggle-collapsed")):(t.expand(),o.setClass("toggle-expanded")),!1),n.add(t)}s.add(n)})),s}}// ./src/sidebar/bookmarks.js
class _ extends b{constructor(e){super();const t=(new u).setClass("list-container"),s=e.strings,n=["sidebar/bookmarks","sidebar/bookmarks/clear"],o=new w(s.get(n[0])).setClass("label"),i=new k("button",s.get(n[1]));i.dom.onclick=t=>{this.clearBookmarks(),e.emit("bookmarked",!1),t.preventDefault()},this.add(new D([o,i]).addClass("header")),this.selector=void 0,this.bookmarks=new S,t.add(this.bookmarks),this.setId("bookmarks"),this.add(t),this.reader=e;const a=()=>{i.dom.disabled=0===e.settings.bookmarks.length};
//-- events --//
e.on("displayed",((e,t)=>{t.bookmarks.forEach((e=>{this.setBookmark(e)})),a()})),e.on("relocated",(e=>{this.locationCfi=e.start.cfi;// save location cfi
})),e.on("bookmarked",((e,t)=>{e?this.appendBookmark():this.removeBookmark(t),a()})),e.on("languagechanged",(e=>{o.setValue(s.get(n[0])),i.setValue(s.get(n[1]))}))}appendBookmark(){const e=this.locationCfi;this.reader.isBookmarked(e)>-1||(this.setBookmark(e),this.reader.settings.bookmarks.push(e))}removeBookmark(e){const t=e||this.locationCfi,s=this.reader.isBookmarked(t);-1!==s&&(this.bookmarks.remove(s),this.reader.settings.bookmarks.splice(s,1))}clearBookmarks(){this.bookmarks.clear(),this.reader.settings.bookmarks=[]}setBookmark(e){const t=new f,s=new I,n=(new m).setClass("btn-remove"),o=this.reader.navItemFromCfi(e);let i,a;if(void 0===o){const t=this.reader.book.spine.get(e);i=t.idref,a=t.idref}else i=o.id,a=o.label;t.setHref("#"+e),t.dom.onclick=t=>{this.selector&&this.selector!==s&&this.selector.unselect(),s.select(),this.selector=s,this.reader.rendition.display(e),t.preventDefault()},t.setTextContent(a),n.dom.onclick=t=>{this.reader.emit("bookmarked",!1,e),t.preventDefault()},s.add([t,n]),s.setId(i),this.bookmarks.add(s)}}// ./src/sidebar/annotations.js
class z extends b{constructor(e){super();const t=(new u).setClass("list-container"),s=e.strings,n=["sidebar/annotations","sidebar/annotations/clear"],o=new w(s.get(n[0])).setClass("label"),i=new k("button",s.get(n[1]));i.dom.onclick=e=>{this.clearNotes(),e.preventDefault()},this.add(new D([o,i]).addClass("header")),this.selector=void 0,this.notes=new S,t.add(this.notes),this.setId("annotations"),this.add(t),this.reader=e,this.update=()=>{i.dom.disabled=0===e.settings.annotations.length},
//-- events --//
e.on("bookready",(e=>{e.annotations.forEach((e=>{this.set(e)})),this.update()})),e.on("noteadded",(e=>{this.set(e),this.update()})),e.on("languagechanged",(e=>{o.setValue(s.get(n[0])),i.setValue(s.get(n[1]))}))}set(e){const t=new f("#"+e.cfi,e.text),s=(new I).setId("note-"+e.uuid),n=(new m).setClass("btn-remove");t.dom.onclick=t=>{this.selector&&this.selector!==s&&this.selector.unselect(),s.select(),this.selector=s,this.reader.rendition.display(e.cfi),t.preventDefault()},n.dom.onclick=t=>{this.removeNote(e),t.preventDefault()},s.add([t,n]),this.notes.add(s),this.reader.rendition.annotations.add("highlight",e.cfi,{},(()=>{}),"note-highlight",{}),this.update()}removeNote(e){const t=this.reader.settings.annotations.indexOf(e);-1!==t&&(this.notes.remove(t),this.reader.settings.annotations.splice(t,1),this.reader.rendition.annotations.remove(e.cfi,"highlight"),this.update())}clearNotes(){this.reader.settings.annotations.forEach((e=>{this.reader.rendition.annotations.remove(e.cfi,"highlight")})),this.notes.clear(),this.reader.settings.annotations=[],this.update()}}// ./src/sidebar/search.js
class F extends b{constructor(e){super();const t=(new u).setClass("list-container"),s=e.strings;let n;const o=new k("search").setId("nav-q");o.dom.placeholder=s.get("sidebar/search/placeholder"),o.dom.onsearch=()=>{const e=o.getValue();0===e.length?this.items.clear():n!==e&&(this.items.clear(),this.doSearch(e).then((e=>{e.forEach((e=>{this.set(e)}))}))),n=e},this.setId("search"),this.items=new S,t.add(this.items),this.add([new D(o),t]),this.reader=e,this.selector=void 0}
/**
	 * Searching the entire book
	 * @param {*} q Query keyword
	 * @returns The search result array.
	 */async doSearch(e){const t=this.reader.book,s=await Promise.all(t.spine.spineItems.map((s=>s.load(t.load.bind(t)).then(s.find.bind(s,e)).finally(s.unload.bind(s)))));return await Promise.resolve([].concat.apply([],s))}set(e){const t=new f("#"+e.cfi,e.excerpt),s=new I;t.dom.onclick=()=>(this.selector&&this.selector!==s&&this.selector.unselect(),s.select(),this.selector=s,this.reader.rendition.display(e.cfi),!1),s.add(t),this.items.add(s)}}// ./src/sidebar/settings.js
class V extends b{constructor(e){super(),super.setId("settings");const t=e.strings,s=["sidebar/settings","sidebar/settings/language","sidebar/settings/fontsize","sidebar/settings/flow","sidebar/settings/spread","sidebar/settings/spread/minwidth","sidebar/settings/theme"],n=new w(t.get(s[0])).setClass("label");this.add(new D(n).addClass("header"));const o=new p(t.get(s[1]),"language-ui"),i=new g,a=(new v).setOptions({zh:"中文",en:"English"});a.dom.onchange=t=>{e.emit("languagechanged",t.target.value)},a.setId("language-ui"),i.add(o),i.add(a);const r=new p(t.get("sidebar/settings/theme"),"theme"),d=new g,l=(new v).setOptions({light:t.get("sidebar/settings/theme/items")[0],dark:t.get("sidebar/settings/theme/items")[1],eyecare:t.get("sidebar/settings/theme/items")[2]});l.dom.onchange=t=>{e.emit("themechanged",t.target.value)},l.setId("theme"),d.add(r),d.add(l);const c=new p(t.get("sidebar/settings/font"),"font"),h=new g,m=(new v).setOptions({default:t.get("sidebar/settings/font/default"),"FZSongKeBenXiuKaiS-R-GB":"方正宋刻本秀楷","Huiwen-HKHei":"汇文港黑","Huiwen-Fangsong":"汇文仿宋体",Bookerly:"Bookerly"});m.dom.onchange=t=>{e.emit("styleschanged",{font:t.target.value})},m.setId("font"),h.add(c),h.add(m);const u=new p(t.get(s[2]),"fontsize"),b=new g,f=new y(100,1);f.dom.onchange=t=>{e.emit("styleschanged",{fontSize:parseInt(t.target.value)})},f.setId("fontsize"),b.add(u),b.add(f);
//-- flow configure --//
const x=new p(t.get(s[3]),"flow"),C=new g,S=t.get("sidebar/settings/pagination"),I=(new v).setOptions({paginated:S[0],scrolled:S[1]});I.dom.onchange=t=>{e.emit("flowchanged",t.target.value),"scrolled"===t.target.value?(z.setValue("none"),z.dom.disabled=!0,T.dom.disabled=!0,e.emit("spreadchanged",{mod:"none",min:void 0})):(z.setValue("auto"),z.dom.disabled=!1,T.dom.disabled=!1,e.emit("spreadchanged",{mod:"auto",min:void 0}))},I.setId("flow"),C.add(x),C.add(I);
//-- spdead configure --//
const T=new y(800,1),B=new p(t.get(s[4]),"spread"),O=new g,_=t.get("sidebar/settings/spread/items"),z=(new v).setOptions({none:_[0],auto:_[1]});z.dom.onchange=t=>{e.emit("spreadchanged",{mod:t.target.value,min:void 0}),T.dom.disabled="none"===t.target.value},z.setId("spread"),O.add(B),O.add(z);const F=new p(t.get(s[5]),"min-spread-width"),V=new g;T.dom.onchange=t=>{e.emit("spreadchanged",{mod:void 0,min:parseInt(t.target.value)})},T.setId("min-spread-width"),V.add(F),V.add(T);
//-- pagination --//
const j=t.get("sidebar/settings/pagination"),A=new g,L=new k("checkbox",!1,j[1]);L.setId("pagination"),L.dom.onclick=e=>{},A.add(new p(j[0],"pagination")),A.add(L),this.add(new D([i,d,h,b,C,O,V])),
//-- events --//
e.on("bookready",(t=>{a.setValue(t.language),l.setValue(t.theme),m.setValue(t.styles.font),t.styles.font||m.setValue("default"),f.setValue(t.styles.fontSize),I.setValue(t.flow),z.setValue(t.spread.mod),T.setValue(t.spread.min),T.dom.disabled="none"===t.spread.mod,e.emit("styleschanged",{font:t.styles.font,fontSize:t.styles.fontSize})})),e.on("layout",(e=>{})),e.on("languagechanged",(e=>{n.setTextContent(t.get(s[0])),o.setTextContent(t.get(s[1])),c.setTextContent(t.get("sidebar/settings/font")),u.setTextContent(t.get(s[2])),x.setTextContent(t.get(s[3]));const i=t.get("sidebar/settings/pagination");I.setOptions({paginated:i[0],scrolled:i[1]}),B.setTextContent(t.get(s[4]));const a=t.get("sidebar/settings/spread/items");z.setOptions({none:a[0],auto:a[1]}),F.setTextContent(t.get(s[5])),r.setTextContent(t.get("sidebar/settings/theme")),l.setOptions({light:t.get("sidebar/settings/theme/items")[0],dark:t.get("sidebar/settings/theme/items")[1],eyecare:t.get("sidebar/settings/theme/items")[2]})}))}}// ./src/sidebar/metadata.js
class j extends b{constructor(e){super();const t=(new u).setClass("list-container"),s=e.strings,n={},o="sidebar/metadata",i=new w(s.get(o)).setClass("label");this.add(new D(i).addClass("header")),n[o]=i,this.items=new S,this.setId("metadata"),this.add(t);const a=(e,t)=>{if(void 0===t[e]||null===t[e]||"string"==typeof t[e]&&0===t[e].length)return;const i=new I,a=(new w).setClass("label"),r=(new w).setClass("value");a.setValue(s.get(o+"/"+e).toUpperCase()),"description"===e?r.dom.innerHTML=t[e]:r.setValue(t[e]),n[o+"/"+e]=a,i.add([a,r]),this.items.add(i)};
//-- events --//
e.on("metadata",(e=>{this.items.clear(),t.clear(),t.add(this.items),document.title=e.title;for(const t in e)a(t,e)})),e.on("languagechanged",(e=>{for(const e in n){let t;t=e===o?s.get(e):s.get(e).toUpperCase(),n[e].setValue(t)}}))}}// ./src/sidebar.js
class A{constructor(e){const t=e.strings,s=e.settings,n=["sidebar/close","sidebar/contents","sidebar/bookmarks","sidebar/annotations","sidebar/search","sidebar/settings","sidebar/metadata"],o=new x("vertical").setId("sidebar"),i=(new u).setId("btn-p").addClass("box"),a=new k("button");a.setTitle(t.get(n[0])),a.dom.onclick=t=>{e.emit("sidebaropener",!1),t.preventDefault(),a.dom.blur()},i.add(a),o.addMenu(i),o.addTab("btn-t",t.get(n[1]),new O(e)),s.bookmarks&&o.addTab("btn-d",t.get(n[2]),new _(e)),s.annotations&&o.addTab("btn-a",t.get(n[3]),new z(e)),o.addTab("btn-s",t.get(n[4]),new F(e)),o.addTab("btn-c",t.get(n[5]),new V(e)),o.addTab("btn-i",t.get(n[6]),new j(e)),o.select("btn-t"),document.body.appendChild(o.dom),
//-- events --//
e.on("sidebaropener",(e=>{e?o.setClass("open"):o.removeAttribute("class")})),e.on("languagechanged",(e=>{a.setTitle(t.get(n[0])),o.setLabel("btn-t",t.get(n[1])),s.bookmarks&&o.setLabel("btn-d",t.get(n[2])),s.annotations&&o.setLabel("btn-a",t.get(n[3])),o.setLabel("btn-s",t.get(n[4])),o.setLabel("btn-c",t.get(n[5])),o.setLabel("btn-i",t.get(n[6]))}))}}// ./src/notedlg.js
class L{constructor(e){const t=(new u).setId("notedlg"),s=e.strings,n=["notedlg/label","notedlg/add"],o=new p(s.get(n[0]),"note-input"),i=new k("text","").setId("note-input");i.dom.oninput=e=>{this.update(),e.preventDefault()};const r=new k("button",s.get(n[1]));r.dom.disabled=!0,r.dom.onclick=s=>{const n={cfi:this.cfi,date:new Date,text:i.getValue(),uuid:a()};this.range=void 0,e.settings.annotations.push(n),e.emit("noteadded",n),t.removeAttribute("class"),s.preventDefault(),r.dom.blur()},this.update=()=>{r.dom.disabled=!(this.range&&i.getValue().length>0)},t.add(new D([o,i,r]).addClass("control")),document.body.appendChild(t.dom),
//-- events --//
e.on("selected",((e,s)=>{this.cfi=e,this.range=s.range(e),this.update(),t.setClass("open");try{const e=this.range.toString().trim(),t=e.length>20?e.substring(0,20)+"...":e;i.setValue(t)}catch(e){console.warn("Could not get selected text:",e),i.setValue("")}})),e.on("unselected",(()=>{this.range=void 0,this.update(),t.removeAttribute("class")})),e.on("languagechanged",(e=>{o.setTextContent(s.get(n[0])),r.setValue(s.get(n[1]))}))}}// ./src/reader.js
class P{constructor(e,t){const s=s=>{const n=new URL(window.location);let o=e;t&&!t.openbook?(o=e,s&&this.storage.clear()):s&&0===n.search.length&&(o=s),this.cfgInit(o,t),
// Apply initial theme to UI
this.applyUITheme(this.settings.theme),this.strings=new l(this),this.toolbar=new T(this),this.content=new B(this),this.sidebar=new A(this),this.settings.annotations&&(this.notedlg=new L(this)),this.init()};this.settings=void 0,this.isMobile=r(),this.storage=new d,this.bid=md5(e).toString().slice(0,8),this.lastLocatinKey=this.bid+"-location";const n=t&&t.openbook;!this.storage.indexedDB||t&&!n?s():this.storage.init((()=>this.storage.get((e=>s(e))))),window.onbeforeunload=this.unload.bind(this),window.onhashchange=this.hashChanged.bind(this),window.onkeydown=this.keyboardHandler.bind(this),window.onwheel=e=>{e.ctrlKey&&e.preventDefault()}}
/**
	 * Initialize book.
	 * @param {*} bookPath
	 * @param {*} settings
	 */init(e,t){this.emit("viewercleanup"),this.navItems={},arguments.length>0&&this.cfgInit(e,t),this.book=ePub(this.settings.bookPath),this.rendition=this.book.renderTo("viewer",{manager:this.settings.manager,flow:this.settings.flow,spread:this.settings.spread.mod,minSpreadWidth:this.settings.spread.min,width:"100%",height:"100%"}),this.book.ready.then((()=>{this.emit("bookready",this.settings);const e=localStorage.getItem(this.lastLocatinKey);this.rendition.display(e||this.display_url).then((()=>{this.loading=!1,this.rendition.on("relocated",(e=>{console.log("Relocated:",e),localStorage.setItem(this.lastLocatinKey,e.start.cfi)}))})),
// Apply styles (theme + font) after book is ready
this.applyStyles()})).then((()=>{this.emit("bookloaded")})),this.book.loaded.metadata.then((e=>{this.emit("metadata",e)})),this.book.loaded.navigation.then((e=>{this.emit("navigation",e)})),this.rendition.on("click",(e=>{"Range"!==e.view.document.getSelection().type&&this.emit("unselected")})),this.rendition.on("layout",(e=>{this.emit("layout",e)})),this.rendition.on("selected",((e,t)=>{this.emit("selected",e,t)})),this.rendition.on("relocated",(e=>{this.emit("relocated",e);
// Re-inject font when page changes
const t="default"===this.settings.styles.font?"":this.settings.styles.font;t&&setTimeout((()=>{this.injectFontWithRetry(t)}),200)})),this.rendition.on("rendered",(()=>{
// Re-inject font when content is rendered
const e="default"===this.settings.styles.font?"":this.settings.styles.font;e&&setTimeout((()=>{this.injectFontWithRetry(e)}),100)})),this.rendition.on("keyup",this.keyboardHandler.bind(this)),this.on("prev",(()=>{"rtl"===this.book.package.metadata.direction?this.rendition.next():this.rendition.prev()})),this.on("next",(()=>{"rtl"===this.book.package.metadata.direction?this.rendition.prev():this.rendition.next()})),this.rendition.on("locationChanged",(e=>{const t=this.rendition.currentLocation();if(t&&t.start){const e=this.book.navigation.get(t.start.href),s=e?e.label:"";t.start.title=s.trim(),console.log("Location:",JSON.stringify(t.start)),this.emit("chapterChanged",s.trim());new URL(window.location.origin)}})),this.on("styleschanged",(e=>{if(e){if(void 0!==e.fontSize){const t=e.fontSize;this.settings.styles.fontSize=t,this.rendition.themes.fontSize(t+"%")}if(void 0!==e.font){let t=e.font;"default"===t&&(t=""),this.settings.styles.font=t,
// Apply styles with new font
this.applyStyles()}}})),this.on("themechanged",(e=>{this.settings.theme=e,
// Apply UI theme
this.applyUITheme(e),
// Apply styles with new theme
this.applyStyles()})),this.on("languagechanged",(e=>{this.settings.language=e})),this.on("flowchanged",(e=>{this.settings.flow=e,this.rendition&&this.rendition.flow(e)})),this.on("spreadchanged",(e=>{void 0!==e.mod&&(this.settings.spread.mod=e.mod,
// Apply spread mode change to rendition
this.rendition&&this.rendition.spread(e.mod,this.settings.spread.min)),void 0!==e.min&&(this.settings.spread.min=e.min,
// Apply minimum spread width change to rendition
this.rendition&&this.rendition.spread(this.settings.spread.mod,e.min))}))}
/* ------------------------------- Common ------------------------------- */
// Helper method to build font URL with configurable assets path
buildFontUrl(e){return`${window.location.origin+window.location.pathname.replace(/\/[^\/]*$/,"/")}${this.settings.assetsPath?this.settings.assetsPath+"/":""}assets/font/${e}`}applyUITheme(e){document.body.className="dark"===e?"dark-theme":"eyecare"===e?"eyecare-theme":""}applyStyles(){if(!this.rendition)return;const e=this.settings.theme,t="default"===this.settings.styles.font?"":this.settings.styles.font,s=t=>{let s={};
// Helper function to add font-family only if font is specified
const n=(e,t)=>(e["font-family"]=t?t+" !important":"Bookerly !important",e);s="dark"===e?{body:n({background:"#1a1a1a",color:"#e0e0e0 !important"},t),p:n({color:"#e0e0e0 !important"},t),"h1, h2, h3, h4, h5, h6":n({color:"#e0e0e0 !important"},t),div:n({},t),span:n({},t),a:n({color:"#4a9eff !important"},t),"a:visited":{color:"#b19cd9 !important"}}:"eyecare"===e?{body:n({background:"#f0f4e8",color:"#2d4a2d !important"},t),p:n({color:"#2d4a2d !important"},t),"h1, h2, h3, h4, h5, h6":n({color:"#2d4a2d !important"},t),div:n({},t),span:n({},t),a:n({color:"#4a7c4a !important"},t),"a:visited":{color:"#6b8e6b !important"}}:{body:n({background:"#fff",color:"#000 !important"},t),p:n({color:"#000 !important"},t),"h1, h2, h3, h4, h5, h6":n({color:"#000 !important"},t),div:n({},t),span:n({},t),a:n({color:"#1a73e8 !important"},t),"a:visited":{color:"#8e24aa !important"}},this.rendition.themes.default(s),t&&this.injectFontWithRetry(t)};s(t||"")}
// Enhanced method to inject font with better timing
injectFontWithRetry(e,t=3){if(!e||"default"===e)return;let s=0;const n=()=>{s++;const o=document.querySelectorAll("#viewer iframe");if(0===o.length&&s<t)return void setTimeout(n,200);let i=0;o.forEach((t=>{try{const s=t.contentDocument||t.contentWindow.document;if(s&&"complete"===s.readyState){
// Create or update the font style element
let t=s.getElementById("injected-font-style");t||(t=s.createElement("style"),t.id="injected-font-style",s.head.appendChild(t));const n={"Huiwen-HKHei":"HuiwenGangHei","Huiwen-Fangsong":"HuiwenFangSong","FZSongKeBenXiuKaiS-R-GB":"FangzhengSongJianKe",Bookerly:"Bookerly-Regular"}[e]||e,o=this.buildFontUrl(`${n}.ttf`),a=`\n\t\t\t\t\t\t\t@font-face {\n\t\t\t\t\t\t\t\tfont-family: '${e}';\n\t\t\t\t\t\t\t\tsrc: url('${o}') format('truetype');\n\t\t\t\t\t\t\t\tfont-weight: normal;\n\t\t\t\t\t\t\t\tfont-style: normal;\n\t\t\t\t\t\t\t}\n\t\t\t\t\t\t`;t.textContent=a,i++}}catch(e){console.warn("Failed to inject font into iframe:",e)}})),0===i&&s<t&&setTimeout(n,200)};n()}navItemFromCfi(e){
// This feature was added to solve the problem of duplicate titles in
// bookmarks. But this still has no solution because when reloading the
// reader, rendition cannot get the range from the previously saved CFI.
const t=this.rendition.getRange(e),s=t?t.startContainer.parentNode.id:void 0,n=this.rendition.currentLocation().start.href;return this.navItems[n+"#"+s]||this.navItems[n]}
/* ------------------------------ Bookmarks ----------------------------- */
/**
	 * Verifying the current page in bookmarks.
	 * @param {*} cfi
	 * @returns The index of the bookmark if it exists, or -1 otherwise.
	 */isBookmarked(e){return this.settings.bookmarks.indexOf(e)}
/* ----------------------------- Annotations ---------------------------- */isAnnotated(e){return this.settings.annotations.indexOf(e)}
/* ------------------------------ Settings ------------------------------ */
/**
	 * Initialize book settings.
	 * @param {any} bookPath
	 * @param {any} settings
	 */cfgInit(e,t){this.entryKey=md5(e).toString(),this.settings={bookPath:e,assetsPath:"",arrows:(this.isMobile,"none"),// none | content | toolbar
manager:"default",restore:!0,history:!0,openbook:!!this.storage.indexedDB,language:"zh",theme:"light",sectionId:void 0,bookmarks:[],// array | false
annotations:[],// array | false
flow:"paginated",// paginated | scrolled
spread:{mod:"auto",// auto | none
min:800},styles:{font:"default",fontSize:100},pagination:void 0,// not implemented
fullscreen:document.fullscreenEnabled},i(t||{},this.settings),this.settings.restore?this.applySavedSettings(t||{}):this.removeSavedSettings()}
/**
	 * Checks if the book setting can be retrieved from localStorage.
	 * @returns true if the book key exists, or false otherwise.
	 */isSaved(){return localStorage&&null!==localStorage.getItem(this.entryKey)}
/**
	 * Removing the current book settings from local storage.
	 * @returns true if the book settings were deleted successfully, or false
	 * otherwise.
	 */removeSavedSettings(){return!!this.isSaved()&&(localStorage.removeItem(this.entryKey),!0)}
/**
	 * Applies saved settings from local storage.
	 * @param {*} external External settings
	 * @returns True if the settings were applied successfully, false otherwise.
	 */applySavedSettings(e){if(!this.isSaved())return!1;let t;try{t=JSON.parse(localStorage.getItem(this.entryKey))}catch(e){console.exception(e)}return!!t&&(i(t,this.settings,e),!0)}
/**
	 * Saving the current book settings in local storage.
	 */saveSettings(){this.settings.previousLocationCfi=this.rendition.location.start.cfi;const e=Object.assign({},this.settings);delete e.arrows,delete e.manager,delete e.history,delete e.restore,delete e.openbook,delete e.pagination,delete e.fullscreen,localStorage.setItem(this.entryKey,JSON.stringify(e))}
//-- event handlers --//
unload(){this.settings.restore&&localStorage&&this.saveSettings()}hashChanged(){const e=window.location.hash.slice(1);this.rendition.display(e)}keyboardHandler(e){let t=this.settings.styles.fontSize;switch(e.key){case"=":case"+":t+=2,this.emit("styleschanged",{fontSize:t});break;case"-":t-=2,this.emit("styleschanged",{fontSize:t});break;case"0":t=100,this.emit("styleschanged",{fontSize:t});break;case"ArrowLeft":this.emit("prev");break;case"ArrowRight":this.emit("next")}}}s(P.prototype);export{P as Reader};
//# sourceMappingURL=epubreader.min-v0.3.5.js.map