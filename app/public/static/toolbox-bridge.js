/**
 * MyBooks Toolbox Bridge
 *
 * 由核心 App 随构建发布，工具前端在自己的 `index.html` 里通过
 * `<script src="/static/toolbox-bridge.js"></script>` 引用，运行时得到
 * `window.MyBooksToolBridge`。
 *
 * 设计见 document/Toolbox_Dynamic_Design.md 4.3/4.5/4.6 节。这是"运行时实现"，跑在真实的
 * MyBooks 页面里；tool_builder（独立仓库）会内置一份 API 形状一致的本地开发 mock 实现，
 * 两者需要保持同步。
 *
 * 纯 ES5+ 原生 JS，不依赖任何构建工具或框架，因为工具作者可以用任意技术栈。
 */
(function (window) {
  'use strict';

  function getQueryParam(name) {
    var params = new URLSearchParams(window.location.search);
    return params.get(name);
  }

  // 工具的 index.html 是从 /get/tool/{tool_id}/index.html 加载的，从当前路径里解析出
  // tool_id，这样同一份 bridge.js 可以被任意工具复用，不需要针对每个工具单独生成。
  function getToolId() {
    var match = window.location.pathname.match(/^\/get\/tool\/([^/]+)\/index\.html$/);
    return match ? match[1] : null;
  }

  var toolId = getToolId();
  // 宿主渲染 <iframe> 时把当前主题/语言拼进 src 的 query string（见 4.3 节），首次渲染就能
  // 拿到，不需要等待 postMessage 握手。此后主题/语言变化不再重设 iframe.src（4.5 节），
  // 而是通过下面的 postMessage 监听实时更新，state 里的值保持最新。
  var state = {
    theme: getQueryParam('theme') || 'light',
    locale: getQueryParam('locale') || 'zh',
  };

  var localeListeners = [];
  var themeListeners = [];

  function onHostMessage(event) {
    if (event.origin !== window.location.origin) return;
    var data = event.data;
    if (!data || data.source !== 'mybooks-toolbox-host') return;

    if (data.type === 'locale-change' && data.locale && data.locale !== state.locale) {
      var oldLocale = state.locale;
      state.locale = data.locale;
      localeListeners.forEach(function (fn) {
        try {
          fn(state.locale, oldLocale);
        } catch (e) {
          // 工具自己的监听器报错不应该打断 bridge 内部状态
        }
      });
    } else if (data.type === 'theme-change' && data.theme && data.theme !== state.theme) {
      var oldTheme = state.theme;
      state.theme = data.theme;
      themeListeners.forEach(function (fn) {
        try {
          fn(state.theme, oldTheme);
        } catch (e) {
          // 同上
        }
      });
    }
  }
  window.addEventListener('message', onHostMessage);

  /**
   * 对 /api/toolbox/tool/{tool_id}/... 的 fetch 简单封装。
   * iframe 与宿主同源，Cookie 天然带上，不需要额外处理鉴权。
   *
   * @param {string} path 相对路径（不需要带前导 /），例如 "ping"
   * @param {RequestInit} [options] 透传给 fetch 的选项
   * @returns {Promise<any>} 解析后的 JSON 响应
   */
  function bridgeFetch(path, options) {
    if (!toolId) {
      return Promise.reject(new Error('MyBooksToolBridge: 无法从当前页面 URL 解析出 tool_id'));
    }
    var cleanPath = String(path || '').replace(/^\//, '');
    var url = '/api/toolbox/tool/' + toolId + '/' + cleanPath;
    var opts = Object.assign({ credentials: 'include' }, options || {});
    return fetch(url, opts).then(function (resp) {
      var contentType = resp.headers.get('content-type') || '';
      if (contentType.indexOf('application/json') !== -1) {
        return resp.json();
      }
      return resp.text();
    });
  }

  /**
   * 请求宿主用它自己的 Vuetify v-snackbar 展示一条提示。可选能力——工具也可以完全自己在
   * iframe 内部画提示条，不依赖这个接口。
   *
   * @param {string} message 提示文案
   * @param {"success"|"error"|"info"|"warning"} [level="info"]
   */
  function bridgeNotify(message, level) {
    window.parent.postMessage(
      {
        source: 'mybooks-toolbox-bridge',
        type: 'notify',
        toolId: toolId,
        message: message,
        level: level || 'info',
      },
      window.location.origin
    );
  }

  /**
   * 订阅宿主语言变化（4.5/4.6 节）。宿主切换 vue-i18n locale 时会通过 postMessage 推送，
   * 不再重新加载 iframe。不调用这个方法也没关系——bridge.locale 本身随时读到的都是最新值，
   * 只是不会主动收到"变了"的推送。
   *
   * @param {(newLocale: string, oldLocale: string) => void} fn
   * @returns {() => void} 取消订阅函数
   */
  function onLocaleChange(fn) {
    localeListeners.push(fn);
    return function unsubscribe() {
      localeListeners = localeListeners.filter(function (f) {
        return f !== fn;
      });
    };
  }

  /**
   * 订阅宿主主题（亮/暗）变化，用法与 onLocaleChange 对称。
   *
   * @param {(newTheme: string, oldTheme: string) => void} fn
   * @returns {() => void} 取消订阅函数
   */
  function onThemeChange(fn) {
    themeListeners.push(fn);
    return function unsubscribe() {
      themeListeners = themeListeners.filter(function (f) {
        return f !== fn;
      });
    };
  }

  /**
   * 自动上报页面内容高度，供宿主把 <iframe> 撑到刚好装下内容（4.3 节的 iframe 承载页原来
   * 用 flex 把 iframe 撑满一个固定 calc(100vh - 64px) 的容器，工具页面一旦比这个高度高，
   * 就只能在 iframe 内部自己出一条纵向滚动条——观感上像是工具页面"被塞进一个小窗口"，
   * 而不是宿主页面本身在滚动。这里不需要工具作者自己调用任何接口：用 ResizeObserver 监听
   * <html> 的实际渲染高度，一变化就自动 postMessage 给宿主（_id.vue 监听后设置
   * iframe.style.height），宿主页面（连同它自带的细滚动条样式）自然接管滚动。
   *
   * 不支持 ResizeObserver 的极老浏览器退化成只在 load/resize 时报一次，没有 iframe 内容
   * 动态变化时的持续跟踪，但不影响首次渲染的高度撑开。
   */
  var lastReportedHeight = 0;
  function reportHeight() {
    if (!toolId) return;
    var height = document.documentElement.scrollHeight;
    if (!height || height === lastReportedHeight) return;
    lastReportedHeight = height;
    window.parent.postMessage(
      { source: 'mybooks-toolbox-bridge', type: 'resize', toolId: toolId, height: height },
      window.location.origin
    );
  }
  if (typeof ResizeObserver !== 'undefined') {
    new ResizeObserver(reportHeight).observe(document.documentElement);
  } else {
    window.addEventListener('load', reportHeight);
    window.addEventListener('resize', reportHeight);
  }
  if (document.readyState === 'complete') {
    reportHeight();
  } else {
    window.addEventListener('load', reportHeight);
  }

  var bridge = {
    toolId: toolId,
    fetch: bridgeFetch,
    notify: bridgeNotify,
    onLocaleChange: onLocaleChange,
    onThemeChange: onThemeChange,
  };
  // theme/locale 用 getter 暴露：取值方式对调用方完全透明（还是读 bridge.theme /
  // bridge.locale），但内部值会随 postMessage 推送实时更新，不需要工具自己维护订阅也能
  // 轮询到最新值。
  Object.defineProperty(bridge, 'theme', {
    get: function () {
      return state.theme;
    },
    enumerable: true,
  });
  Object.defineProperty(bridge, 'locale', {
    get: function () {
      return state.locale;
    },
    enumerable: true,
  });

  window.MyBooksToolBridge = bridge;
})(window);
