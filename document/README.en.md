[![GitHub License](https://img.shields.io/github/license/poxenstudio/talebook?style=flat-square)](https://github.com/poxenstudio/talebook/blob/master/LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)](https://hub.docker.com/r/poxenstudio/talebook)
![GitHub stars](https://img.shields.io/github/stars/PoxenStudio/talebook.svg?logo=github)


# TaleBook: Personal Calibre WebServer
An enhanced personal books management web server built on Calibre + Vue, beautiful and easy to use. ([Chinese](../README.md))

## A Simple and Practical Personal Library System
This project is developed based on [talebook](https://github.com/talebook/talebook). It focuses on personal and family management of eBooks and physical books, plus multi-account reading management. It is not intended for public book-site operation.

The long-term direction is to integrate AI for extended reading and knowledge organization, building a personal knowledge base.

![Example](example.jpg)

This system is not an eBook reader itself. Its core value is library management. You can choose any reader app you like. On desktop, Koodo Reader is recommended.

**Important notice: In mainland China, operating a public online publishing/book site as an individual is not permitted. This project is intended for personal use only.**

### Project Highlights (Added in poxenstudio/talebook)
* Watch import folders and auto-import new books.
* Provide Podcast service (turn your library into podcasts).
* Support WebDAV connection and synchronization.
* Push books to Kindle and devices that support Wi-Fi transfer.
* Support custom categories.
* Support physical book records.
* Support reading-status management.
* Integrate epub2audio to generate audiobooks from EPUB.
* Upgrade to Calibre 7.6 on Ubuntu 24.04.
* Support searching both Simplified and Traditional Chinese.
* Support EPUB/AZW3 conversion in both directions.
* Support private-visibility books (visible to uploader only).
* Improved UI style with dark mode.
* Support icon switching and user avatar settings.
* Reader supports color themes and font switching (4 built-in fonts).

### Original TaleBook Features
Below is the original TaleBook feature set.

TaleBook is a simple personal library management system based on Calibre with **online reading** support.

* Beautiful UI: the default Calibre web UI is not user-friendly; TaleBook provides a Vue-based interface for desktop and mobile.
* Multi-user support: supports multi-account usage and social login via ~~Douban~~ (deprecated), QQ, Weibo, GitHub, etc.
* Online reading: uses [epub.js](https://github.com/intity/epubreader-js) for in-browser reading (chapter comments are in development).
* Batch scanning and importing.
* Email push to Kindle.
* OPDS support for apps such as [KyBooks](http://kybook-reader.com/).
* One-click web installation and initialization.
* Optimized file paths for large libraries (letter-based or Chinese filename retention).
* Quick metadata updates via Baidu Baike and Douban sources.
* Private mode with access code, suitable for small-circle sharing.

### Web API
[Web API Documentation](WebAPI.md)

### Follow the Project
WeChat public account: Talebook

![Talebook](gongzhonghao_talebook.jpg)


## Roadmap
* In planning
        1. Information sharing and AI-assisted capabilities (large change, will be delivered incrementally).
        2. File encryption for private deployments (mitigate file usability issues caused by platform scans).
        3. EPUB export with watermark (TBD).


## Docker ![Docker Pulls](https://img.shields.io/docker/pulls/poxenstudio/talebook.svg)

Deployment is straightforward. Docker is recommended.
Image: [Docker Hub](https://hub.docker.com/r/poxenstudio/talebook)

* Built on Ubuntu 24.04 + Calibre 7.6 for better compatibility.
* Do not set Docker UID/GID to root (ID: 0).

Using docker-compose is recommended. Download [docker-compose.yml](../docker-compose.yml) and start:

```bash
wget https://raw.githubusercontent.com/PoxenStudio/talebook/master/docker-compose.yml
docker-compose -f docker-compose.yml up -d
```

If you need custom mount paths or ports, edit docker-compose.yml first.

If using plain docker:

```bash
docker run -d --name talebook -p <local_port>:80 -v <local_data_dir>:/data poxenstudio/talebook
```

Example:

```bash
docker run -d --name talebook -p 8080:80 -v /tmp/demo:/data poxenstudio/talebook
```


## Connect via WebDAV
WebDAV URL: `http://<ip_or_domain>:<port>/books`

* On macOS
Use Connect to Server and enter the URL:

![WebDAV_macOS](webdav_macOS.png)

* On Windows
If HTTPS is not enabled, configure WebClient to allow HTTP first:

```text
1. Open Registry Editor (Run -> regedit)
2. Go to HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\WebClient\Parameters
     and set BasicAuthLevel to 2
3. Run PowerShell as Administrator:
     net stop webclient
     net start webclient
```

Then map a network drive to the WebDAV URL:

![WebDav_Windows](webdav_Windows.png)

Explorer view:

![WebDAV_Windows_Explorer](webdav_Window_2.png)


## Use MCP Service
From v3.15.0, TaleBook supports MCP service integration with AI tools.
Current flow may require account login information before use.

```json
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


## Use TaleBook Skill
See [TaleBook Skill](https://clawhub.ai/poxenstudio/talebook).


## FAQ
For common issues, see [User Guide](UserGuide.zh_CN.md).
If unresolved, open an issue or send a private message via the official account.

For manual installation, see [Developer Guide](Development.zh_CN.md).

NAS setup references:
[Post 1](https://post.smzdm.com/p/a992p6e0/),
[Post 2](https://post.smzdm.com/p/a3d7ox0k/),
[Post 3](https://odcn.top/2019/02/26/2734/),
[FnOS](https://club.fnnas.com/forum.php?mod=viewthread&tid=27403)

**Disclaimer:** This project does not operate or maintain any public library sites. Community sites such as joyeuse and wenyuange are user-built. Please do not contact the author about those deployments.


## Contributors
[![](https://contrib.rocks/image?repo=PoxenStudio/talebook)](https://github.com/PoxenStudio/talebook/graphs/contributors)


## Project Homepage
[PoxenStudio TaleBook](https://mybooks.top)


## Contact
📧 [poxenstudio@gmail.com](mailto:poxenstudio@gmail.com)
