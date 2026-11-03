#!/usr/bin/env python3
import base64
import html
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


SINCE = "2025-06-01T00:00:00Z"
PAGE_SIZE = 100
AVATAR_SIZE = 64
CELL_SIZE = 72
COLUMNS = 8
ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "document/images/contributors.svg"


def github_request(url, accept, token=None):
    headers = {
        "Accept": accept,
        "User-Agent": "MyBooks-contributors-image",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, headers=headers)
    try:
        return urlopen(request, timeout=30)
    except HTTPError as error:
        raise RuntimeError(f"GitHub API request failed ({error.code}): {url}") from error


def fetch_contributors(repository):
    contributors = {}
    page = 1
    token = os.environ.get("GITHUB_TOKEN")
    while True:
        query = urlencode(
            {"since": SINCE, "per_page": PAGE_SIZE, "page": page}
        )
        url = f"https://api.github.com/repos/{repository}/commits?{query}"
        with github_request(
            url, "application/vnd.github+json", token=token
        ) as response:
            commits = json.load(response)
        if not commits:
            break
        for commit in commits:
            author = commit.get("author")
            if author and author.get("login"):
                contributors.setdefault(
                    author["login"],
                    {"login": author["login"], "avatar_url": author["avatar_url"]},
                )
        if len(commits) < PAGE_SIZE:
            break
        page += 1
    return list(contributors.values())


def fetch_avatar(avatar_url):
    parts = urlsplit(avatar_url)
    query = urlencode(parse_qsl(parts.query) + [("s", str(AVATAR_SIZE))])
    avatar_url = urlunsplit(parts._replace(query=query))
    with github_request(avatar_url, "image/*") as response:
        content_type = response.headers.get_content_type()
        if content_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise RuntimeError(f"Unsupported avatar image type: {content_type}")
        return content_type, base64.b64encode(response.read()).decode("ascii")


def create_svg(contributors):
    if not contributors:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="32" '
            'viewBox="0 0 640 32" role="img">'
            '<text x="0" y="22" font-family="sans-serif" font-size="16">'
            "No contributors since 2025-06-01</text></svg>\n"
        )

    rows = (len(contributors) + COLUMNS - 1) // COLUMNS
    columns = min(len(contributors), COLUMNS)
    width = columns * CELL_SIZE
    height = rows * CELL_SIZE
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" role="img">',
        '<title>MyBooks contributors since 2025-06-01</title>',
    ]
    for index, contributor in enumerate(contributors):
        x = (index % COLUMNS) * CELL_SIZE + (CELL_SIZE - AVATAR_SIZE) // 2
        y = (index // COLUMNS) * CELL_SIZE + (CELL_SIZE - AVATAR_SIZE) // 2
        mime_type, image_data = fetch_avatar(contributor["avatar_url"])
        login = html.escape(contributor["login"])
        parts.extend(
            [
                f'<g><title>{login}</title>',
                f'<clipPath id="avatar-{index}"><circle cx="{x + 32}" '
                f'cy="{y + 32}" r="32"/></clipPath>',
                f'<image x="{x}" y="{y}" width="{AVATAR_SIZE}" '
                f'height="{AVATAR_SIZE}" clip-path="url(#avatar-{index})" '
                f'xlink:href="data:{mime_type};base64,{image_data}"/>',
                "</g>",
            ]
        )
    parts.append("</svg>\n")
    return "".join(parts)


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "PoxenStudio/mybooks")
    if repository.count("/") != 1:
        raise ValueError(f"Invalid GitHub repository name: {repository}")
    contributors = fetch_contributors(repository)
    svg = create_svg(contributors)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(svg, encoding="utf-8")
    print(
        f"Generated {OUTPUT.relative_to(ROOT)} for {len(contributors)} "
        f"contributors since 2025-06-01"
    )


if __name__ == "__main__":
    main()
