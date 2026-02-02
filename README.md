[![GitHub License](https://img.shields.io/github/license/poxenstudio/talebook?style=flat-square)](https://github.com/poxenstudio/talebook/blob/master/LICENSE)
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
* 支持以WebDAV连接及数据同步
* 支持推送到支持Wifi传书的设备及Kindle上
* 支持自定义分类
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
公众号```Talebook```
![Talebook](document/gongzhonghao_talebook.jpg)


## 版本
* 待开发
    1. 支持信息共享及AI协助的功能。是一个大的修改，会分成几步完成。
    2. 增加文件的加密处理。可以帮助解决私有化部署场景下平台扫描导致的文件无法使用的问题。
    3. 带水印导出epub (待定)
## Docker ![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)

部署比较简单，建议采用docker，镜像地址：[dockerhub](https://hub.docker.com/r/poxenstudio/talebook)
* 已经调整基于```Ubuntu 24.04```和```Calibre 7.6```构建, 改善兼容性。Docker运行的UID/GID不要设置为```root```(ID:0)。

推荐使用`docker-compose`，下载仓库中的配置文件[docker-compose.yml](docker-compose.yml)，然后执行命令启动即可。
若希望修改挂载的目录或端口，请修改docker-compose.yml文件。

```
wget https://raw.githubusercontent.com/PoxenStudio/talebook/master/docker-compose.yml
docker-compose -f docker-compose.yml  up -d
```


如果使用原生docker，那么执行命令：

`docker run -d --name talebook -p <本机端口>:80 -v <本机data目录>:/data poxenstudio/talebook`


例如

`docker run -d --name talebook -p 8080:80 -v /tmp/demo:/data poxenstudio/talebook`

## 使用WebDAV连接
WebDAV URL地址: `http://<ip or domain>:<port>/books`
* macOS下
在`连接到服务器`输入对应的URL进行连接:
![WebDAV_macOS](document/webdav_macOS.png)

* Windows下
如果未配置https, 需要先将WebClient修改为支持HTTP协议：
```
1. 打开注册表, (运行->输入regedit)
2. 找到 HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\WebClient\Parameters, 将BasicAuthLevel改为2
3. 以超级管理员身份运行PowerShell, 先入输入net stop webclient 和 net start webclient.
```
然后通过`映射网络驱动器`连接到指定URL：
![WebDav_Windows](document/webdav_Windows.png)
访问列表:
![WebDAV_Windows_Explorer](document/webdav_Window_2.png)

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

常见问题请参阅[使用指南](document/UserGuide.zh_CN.md)，无法解决的话，提个ISSUE, 或进入公众号私信。

手动安装请参考[开发者指南](document/Development.zh_CN.md)

NAS安装指南：请参考网友们的帖子：[帖子1](https://post.smzdm.com/p/a992p6e0/)，[帖子2](https://post.smzdm.com/p/a3d7ox0k/), [帖子3](https://odcn.top/2019/02/26/2734/), * [飞牛NAS](https://club.fnnas.com/forum.php?mod=viewthread&tid=27403)

**如果觉得本项目很棒，欢迎前往[爱发电](https://afdian.net/@talebook)，赞助作者，持续优化，为爱充电！**

**再次声明！本项目没有维护任何公开的书库站点，例如 joyeuse, wenyuange 等网站均属于网友搭建的，相关问题请不要咨询我，爱莫能助！**


## 贡献者
[![](https://contrib.rocks/image?repo=PoxenStudio/talebook)](https://github.com/PoxenStudio/talebook/graphs/contributors)


## 演示
[Demo站点（密码 admin/demodemo ）](http://demo.talebook.org)

## 项目首页
[PoxenStudio Talebook](https://mybooks.top)
