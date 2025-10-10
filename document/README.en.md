[![GitHub License](https://img.shields.io/github/license/talebook/talebook?style=flat-square)](https://github.com/talebook/talebook/blob/master/LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)](https://hub.docker.com/r/poxenstudio/talebook)


# Tale Book: Personal Calibre WebServer
A enhanced personal books management webserver built on Calibre + Vue, beautiful and easy-to-use. ([中文说明](document/README.zh_CN.md))

**Noted: Online publishing is prohibited for personal websites in China. This project is recommended for personal use only!**

## Road Map
* v3.9.0 (Completed)
    1. Updated to Calibre 7.6, system uses Ubuntu 24.04.
    2. Added information reset functionality in management, updated when scraping occurs
* v3.10.0 (Completed)
    1. Introduce book export functionality (e.g., converting epub to azw3 for Kindle use)
    2. Search both in simplified chinese and traditional chinese
* NEXT
    1. Support for information sharing

## Introduction
Tale Book is a simple yet powerful personal book management system based on Calibre, supporting **online reading**. Key features include:
* **Beautiful and intuitive UI**: The default Calibre web interface is unattractive and difficult to use. Tale Book introduces a new interface built with Vue, optimized for both PC and mobile browsing.
* **Multi-user support**: Enables multi-user functionality for easier management, supporting login via ~~Douban~~ (deprecated), QQ, Weibo, GitHub, and other social platforms.
* **Online reading**: Allows users to read eBooks online using the [epub.js](https://github.com/intity/epubreader-js) library (chapter review functionality is under development).
* **Batch scanning and importing**: Quickly scan and import books into the library.
* **Email push**: Easily send books to Kindle devices.
* **OPDS support**: Compatible with apps like [KyBooks](http://kybook-reader.com/) for convenient reading.
* **One-click installation**: Provides web-based initialization for effortless website setup.
* **Optimized file storage**: Supports categorization by letter or retaining Chinese filenames for large libraries.
* **Quick book information updates**: Enables importing basic book information from Baidu Encyclopedia and Douban searches.
* **Private mode**: Requires an access code to enter the website, ideal for sharing within small groups.

This project was formerly known as `calibre-webserver`.

## Docker ![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)

Deployment is straightforward, and Docker is recommended. The Docker image is available on [Docker Hub](https://hub.docker.com/r/poxenstudio/talebook).
* Built on `Ubuntu 24.04` and `Calibre 7.6` for improved compatibility. Avoid setting Docker's UID/GID to `root` (ID: 0).

### Using Docker Compose
Download the configuration file [docker-compose.yml](docker-compose.yml) from the repository and execute the following command to start:
```bash
wget https://raw.githubusercontent.com/HorkyChen/talebook/master/docker-compose.yml
docker-compose -f docker-compose.yml up -d
```

### Using Native Docker
Run the following command:
```bash
docker run -d --name talebook -p <local port>:80 -v <local data directory>:/data poxenstudio/talebook
```

For example:
```bash
docker run -d --name talebook -p 8080:80 -v /tmp/demo:/data poxenstudio/talebook
```

## FAQ

For common issues, refer to the [User Guide](document/UserGuide.zh_CN.md). If unresolved, submit an issue or [join the QQ group for discussion](https://qm.qq.com/q/5lSfpJGsBq).

For manual installation, consult the [Developer Guide](document/Development.zh_CN.md).

### NAS Installation Guide
Refer to the following user posts:
* [Post 1](https://post.smzdm.com/p/a992p6e0/)
* [Post 2](https://post.smzdm.com/p/a3d7ox0k/)
* [Post 3](https://odcn.top/2019/02/26/2734/)
* [FnOS](https://club.fnnas.com/forum.php?mod=viewthread&tid=27403)

**Disclaimer**: This project does not maintain any public book library sites, such as joyeuse, wenyuange, etc., which are built by users. Please do not consult the author regarding related issues, as assistance cannot be provided.

## Contributors
[![](https://contrib.rocks/image?repo=HorkyChen/talebook)](https://github.com/HorkyChen/talebook/graphs/contributors)

## Demonstration

[Demo site (password: admin/demodemo)](http://demo.talebook.org)

[Video introduction (thanks to @Pan06da)](https://player.bilibili.com/player.html?aid=482258810&bvid=BV1AT411S7c3&cid=1018595245&page=1)

Screenshots of the project demonstration:
![](document/screenshot.png)
