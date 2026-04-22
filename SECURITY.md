# Security Policy

本项目主要面向个人或家庭自用的书库管理场景，不建议用于网站搭建，也不建议直接暴露到公网。

## Supported Versions

以下范围内的版本会优先接收安全修复：

| Version | Supported |
| --- | --- |
| `master` 最新代码 | Yes |
| 最近一个稳定发布版本 | Yes |
| 更早的历史版本 | No |

如果你在较老版本中发现安全问题，请先尝试复现于最新代码或最近一个稳定发布版本。

## Reporting a Vulnerability

如果你发现了安全漏洞，请不要公开提交 Issue、不要在讨论区披露细节，也不要直接公开利用方式。

请通过以下方式私下联系：

- 邮箱：poxenstudio@gmail.com

建议在邮件中提供以下信息：

- 漏洞类型与影响范围
- 受影响的版本、部署方式和配置前提
- 复现步骤或 PoC
- 可能的修复建议（如果有）
- 你的联系方式，以及是否希望在修复公告中署名

邮件标题建议使用：`[security] PoxenStudio/Talebook Vulnerability Report`

## Response Process

收到报告后，项目会尽量按以下流程处理：

1. 会尽快时间内确认已收到报告。（也可以微信公众号上私信提醒）
2. 评估漏洞影响、可利用条件和修复范围。
3. 在修复完成前尽量避免公开披露细节。
4. 修复后通过提交记录或版本发布对外说明。

具体响应时间不作 SLA 承诺，但会尽量优先处理可导致以下问题的漏洞：

- 未授权访问
- 权限提升
- 任意文件读取或写入
- 远程代码执行
- 敏感信息泄露

## Deployment Recommendations

如果你自行部署本项目，建议至少做到以下几点：

- 不要将管理后台或初始化页面直接暴露到公网。
- 为管理员账号使用强密码，并避免复用密码。
- 使用 HTTPS，避免在明文 HTTP 下传输登录凭据。
- 限制对 WebDAV、MCP、OPDS 等接口的外网访问范围。
- 妥善保护 SMTP、第三方 API、对象存储等密钥和凭据。
- 及时更新到最新版本，并同步更新依赖与容器镜像。
- 为公开可访问的实例配置反向代理、访问控制和日志监控。

## Scope

以下内容通常不视为单独的安全漏洞：

- 仅在用户已拥有管理员权限前提下才能完成的操作
- 仅影响本地开发环境、测试环境或非默认调试配置的问题
- 由于弱密码、错误公网暴露、未启用 HTTPS 等部署不当导致的风险
- 第三方组件自身已知但尚未在本项目可利用路径中形成实际影响的问题

如果你不确定某个问题是否属于安全漏洞，仍然可以先通过邮件私下联系。

## English Summary

Please report security vulnerabilities privately to poxenstudio@gmail.com instead of opening a public issue. Include affected version, reproduction steps, impact, and any proof of concept. Public disclosure should wait until a fix is available.