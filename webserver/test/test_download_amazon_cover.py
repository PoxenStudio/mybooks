import requests

CHROME_HEADERS = {
    "Accept-Language": "zh-CN,zh;q=0.8,zh-TW;q=0.6",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36"
}

url = "https://m.media-amazon.com/images/I/81aY1lxk+9L._SL1500_.jpg"

headers = dict(CHROME_HEADERS)
headers["Referer"] = url
r = requests.get(url, headers=headers, verify=False, timeout=10)

# write the content of the response to temp file
with open("./amazon_cover.jpg", "wb") as f:
    f.write(r.content)
