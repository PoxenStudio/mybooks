使用指南
===========
本文主要介绍MyBooks的使用说明，以及常见问题。如需手动安装或者提交PR，请参阅[开发者指南](./Development.zh_CN.md)。


NAS用户，可以参阅网友们写的指南：
* [新手向NAS教程 篇十七：春节假期来搭建书库吧！免费开源有手就行！群晖Calibre部署教程！ ](https://post.smzdm.com/p/a3d7ox0k/)
* [飞牛NAS部署MyBooks(PoxenStudio/Talebook)](https://club.fnnas.com/forum.php?mod=viewthread&tid=27403)


常见配置指南
===========
请参考[功能手册](https://mybooks.top/talebook/features.html)。
注: 所有功能说明以公众号Talebook上发布的版本说明为准。

常见问题排查
===============
### supervisord启动失败

如果有调整过supervisord里面的配置（例如端口、目录），一定要执行```sudo supervisorctl reload all```重新读取配置，不然是不会生效的，可能会导致启动失败。

如果提示```mybooks:tornado-8000: ERROR(spawn error)```，那么说明环境没配置正确。
请打开日志文件```/data/log/mybooks.log```查看原因，重点查看最后一次出现Traceback报错，关注其中```Traceback (most recent call last)```提示的错误原因。

### 网站能打开，但是提示```500: internal server error```

这种情况，一般是服务运行时出现异常，常见原因有目录权限没有配置正常、数据库没创建好、或者触发了某个代码BUG。

** 一般都是因为data目录权限设置不正确，导致启动异常 **，可以多排查下用户名、UID、目录权限等。

请打开日志文件```/data/log/mybooks.log```查看原因，重点查看最后一次出现Traceback报错，关注其中```Traceback (most recent call last)```提示的错误原因，并提issue联系开发者排查。

### 「静读天下」APP里访问书库会失败，怎么办？

这是因为静读天下APP不支持Cookie，导致登录会失败。在最新版系统中(v2.0.0-87-gf6d8f06)已经调整程序逻辑，可以无需登录就正常浏览，仅在下载时检测权限。为了避免弹出登录提示，请配置：
 - 关闭「私人图书馆」模式。
 - 打开「允许任意下载」（访客无需注册或登录）

### 阅读器的页面卡住了，不加载书籍，怎么办？

 这是因为浏览器的广告拦截插件屏蔽了一些JS，导致页面加载异常。请关闭相关插件后再重试，例如 uBlock Origin

