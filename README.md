[![GitHub License](https://img.shields.io/github/license/talebook/talebook?style=flat-square)](https://github.com/talebook/talebook/blob/master/LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)](https://hub.docker.com/r/poxenstudio/talebook)


# TaleBook: Personal Calibre WebServer
An enhanced personal books management webserver built on Calibre + Vue, beautiful and easy-to-use. ([English](document/README.en.md))

与阅读器不同，主要功能是对电子书的管理功能。阅读器可以灵活选择，移动端比较多，在PC端推荐Koodo Reader。

## 简单好用的个人图书管理系统
本项目基于talebook开发维护, 原项目地址:[talebook](https://github.com/talebook/talebook)。 后续目标是结合AI提供更多的扩展阅读内容，形成个人的知识库。
![Example](document/example.jpg)

**友情提醒：中国境内网站，个人是不允许进行在线出版的，维护公开的书籍网站是违法违规的行为！建议仅作为个人使用！**

### 项目介绍
poxenstudio/talebook增加的特性包括:
* 支持添加实体书
* 支持阅读管理
* 集成epub2audio将epub转换有声书
* 更新Calibre 7.6，系统使用Ubuntu 24.04
* 支持中文搜索时，使用简繁体同时搜索
* 支持epub与azw3互转
* 支持将图书指定为私藏模式，仅有上传者可见
* UI风格美化 - 增加暗黑模式
* 支持切换不同图标，支持设置用户头像
* 支持书栈推书的功能 每天推送2~5书，以社科、历史为主
* 阅读器支持颜色样式切换，字体切换(提供4个内置字体)

以下为talebook的介绍。
这是一个基于Calibre的简单的个人图书管理系统，支持**在线阅读**。主要特点是：
* 美观的界面：由于Calibre自带的网页太丑太难用，于是基于Vue，独立编写了新的界面，支持PC访问和手机浏览；
* 支持多用户：为了网友们更方便使用，开发了多用户功能，支持~~豆瓣~~（已废弃）、QQ、微博、Github等社交网站的登录；
* 支持在线阅读：借助[epub.js](https://github.com/intity/epubreader-js) 库，支持了网页在线阅读电子书（章评功能开发中）；
* 支持批量扫描导入书籍；
* 支持邮件推送：可方便推送到Kindle；
* 支持OPDS：可使用[KyBooks](http://kybook-reader.com/)等APP方便地读书；
* 支持一键安装，网页版初始化配置，轻松启动网站；
* 优化大书库时文件存放路径，可以按字母分类、或者文件名保持中文；
* 支持快捷更新书籍信息：支持从百度百科、豆瓣搜索并导入书籍基础信息；
* 支持私人模式：需要输入访问码，才能进入网站，便于小圈子分享网站；

### Web API
[Web API文档](document/WebAPI.md)

### 关注项目

公众号```talebook```

![talebook](document/gongzhonghao_talebook.jpg)

微信扫码加好友, 备注```talebook```

![微信号PoxenStudio](document/weichat_poxenstudio.jpg)


## 版本
* 待开发
    1. 支持信息共享及AI协助的功能。是一个大的修改，会分成几步完成。
    2. 增加文件的加密处理。可以帮助解决私有化部署场景下平台扫描导致的文件无法使用的问题。
    3. 带水印导出epub (待定)
    4. 增加统计信息显示
* v3.20.0
    1. 建图书标签库, 优化标签展示和关联推荐
* v3.19.0
    1. 优化有声书播放功能
* v3.18.0
    1. 增加实体书管理功能
    2. 增加阅读管理功能
* v3.17.0 (完成)
    1. 优化文件扫描导入
    2. 增加版本更新通知
* v3.16.* (完成)
    1. 支持封面设置
    2. 解决飞牛移动端无法登录的问题
* v3.15.* (完成)
    1. 提供MCP Server，可以集成到AI工具中使用
    2. 侧边栏增加图书语言分类，图书信息中支持修改语言类别
    3. 修复之前热度榜单无显示的问题
* v3.14.0 (完成)
    1. EPUB转语音
* v3.13.* (完成)
    1. 阅读器支持颜色样式切换，字体切换(提供4个内置字体)，精简语言
* v3.12.* (完成)
    1. 支持书栈推书的功能 (增加书栈后台服务)
    2. 修复反馈的几个问题，支持切换不同图标，支持设置用户头像 （v3.12.1 & v3.12.2）
* v3.11.* (完成)
    1. UI风格美化 - 增加暗黑模式 (v3.11.0)
    2. 支持将图书指定为私藏模式，仅有上传者可见 (v3.11.0)
* v3.10.0 (完成)
    1. 增加图书导出功能 (epub与azw3互转， 方便kindle使用。 增加了内嵌字体，避免在kindle无法调整字体)
    2. 支持中文搜索时，使用简繁体同时搜索
    3. 支持UI切换语言, 解决初次使用的语言问题（后台返回的文本没有处理）
* v3.9.0 (完成)
    1. 更新Calibre 7.6，系统使用Ubuntu 24.04

## Docker ![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)

部署比较简单，建议采用docker，镜像地址：[dockerhub](https://hub.docker.com/r/poxenstudio/talebook)
* 已经调整基于```Ubuntu 24.04```和```Calibre 7.6```构建, 改善兼容性。Docker运行的UID/GID不要设置为```root```(ID:0)。

推荐使用`docker-compose`，下载仓库中的配置文件[docker-compose.yml](docker-compose.yml)，然后执行命令启动即可。
若希望修改挂载的目录或端口，请修改docker-compose.yml文件。

```
wget https://raw.githubusercontent.com/HorkyChen/talebook/master/docker-compose.yml
docker-compose -f docker-compose.yml  up -d
```


如果使用原生docker，那么执行命令：

`docker run -d --name talebook -p <本机端口>:80 -v <本机data目录>:/data poxenstudio/talebook`


例如

`docker run -d --name talebook -p 8080:80 -v /tmp/demo:/data poxenstudio/talebook`


## 使用MCP Service
从v3.15.0开始，支持MCP服务，可以集成到AI工具中使用。现在使用流程会提示提供账号信息进行登录，然后才能正常使用。
```
{
  "mcpServers": {
    "talebook": {
      "type": "streamableHttp",
      "url": "http://<ip>:<port>/api/mcp/stream",
      "description": "Local ebooks management system"
    }
  }
}
```


## 常见问题

常见问题请参阅[使用指南](document/UserGuide.zh_CN.md)，无法解决的话，提个ISSUEE，[进Q群交流](https://qm.qq.com/q/5lSfpJGsBq)

手动安装请参考[开发者指南](document/Development.zh_CN.md)

NAS安装指南：请参考网友们的帖子：[帖子1](https://post.smzdm.com/p/a992p6e0/)，[帖子2](https://post.smzdm.com/p/a3d7ox0k/), [帖子3](https://odcn.top/2019/02/26/2734/), * [飞牛NAS](https://club.fnnas.com/forum.php?mod=viewthread&tid=27403)

**如果觉得本项目很棒，欢迎前往[爱发电](https://afdian.net/@talebook)，赞助作者，持续优化，为爱充电！**

**再次声明！本项目没有维护任何公开的书库站点，例如 joyeuse, wenyuange 等网站均属于网友搭建的，相关问题请不要咨询我，爱莫能助！**


## 贡献者
[![](https://contrib.rocks/image?repo=HorkyChen/talebook)](https://github.com/HorkyChen/talebook/graphs/contributors)


## 演示

[Demo站点（密码 admin/demodemo ）](http://demo.talebook.org)

[视频简介（感谢@Pan06da的制作）](https://player.bilibili.com/player.html?aid=482258810&bvid=BV1AT411S7c3&cid=1018595245&page=1)


项目演示截图如下：
![](document/screenshot.png)
