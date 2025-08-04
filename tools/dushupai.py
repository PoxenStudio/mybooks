import requests
from bs4 import BeautifulSoup
import time
import datetime
import os
from urllib.parse import urlparse, parse_qs, quote, unquote
import re
from ctfile_downloader import CTFileDownloader

def get_dushupai_books(skip_count=10, downloaded_books={}):
    base_url = "https://www.dushupai.com"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Referer": base_url
    }

    book_data = []

    try:
        # 获取首页内容
        home_response = requests.get(base_url, headers=headers, timeout=10)
        home_response.raise_for_status()
        home_soup = BeautifulSoup(home_response.text, 'html.parser')

        # 定位图书列表
        book_list = home_soup.select('ul.portfolio-book > li')
        if not book_list:
            print("未找到图书列表")
            return book_data

        print(f"找到 {len(book_list)} 本图书")

        # 遍历每本图书
        for idx, book_item in enumerate(book_list):
            if idx < skip_count:
                continue

            try:
                # 提取标题和ID
                book_div = book_item.select_one('div.book')
                if not book_div:
                    continue

                title_link = book_div.find('a')
                if not title_link:
                    continue

                # 从title属性获取书名
                book_title = title_link.get('title', '').strip()
                if not book_title:
                    # 如果title属性不存在，尝试从文本获取
                    book_title = title_link.get_text(strip=True)

                # 从href属性提取ID
                href = title_link.get('href', '')
                id_match = re.search(r'book-content-(\d+)\.html', href)
                if not id_match:
                    print(f"跳过 {book_title}: 无法提取书本ID")
                    continue

                book_id = id_match.group(1)
                if int(book_id) in downloaded_books:
                    print(f"跳过 {book_title}: 已下载")
                    break

                # 构造下载页面URL
                download_url = f"{base_url}/download-book-{book_id}.html"

                # 获取下载页面
                time.sleep(1)  # 礼貌性延迟
                download_response = requests.get(download_url, headers=headers, timeout=10)
                download_response.raise_for_status()
                download_soup = BeautifulSoup(download_response.text, 'html.parser')

                # 提取下载链接
                download_block = download_soup.select_one('div.download_blcok')
                download_links = []

                if download_block:
                    # 找到所有下载按钮
                    for btn in download_block.select('div.button'):
                        link = btn.find('a')
                        if link and link.get('href'):
                            download_links.append(link['href'])

                if download_links:
                    book_data.append({
                        "title": book_title,
                        "id": book_id,
                        "download_page": download_url,
                        "download_links": download_links
                    })
                    print(f"已处理 ({idx+1}/{len(book_list)}): {book_title} (ID: {book_id})")
                else:
                    print(f"跳过 {book_title}: 未找到下载链接")

            except Exception as e:
                print(f"处理图书时出错: {str(e)}")
                continue

    except Exception as e:
        print(f"主流程出错: {str(e)}")
        # show the call stack
        import traceback
        traceback.print_exc()

    return book_data

if __name__ == "__main__":
    recommedded_cnt = 10
    downloaded_books = {64140, 64139}
    books = get_dushupai_books(recommedded_cnt, downloaded_books)

    print("\n最终结果:")
    for book in books:
        print(f"\n书名: {book['title']}")
        print(f"书本ID: {book['id']}")
        print(f"下载页面: {book['download_page']}")
        print("下载链接:")
        for i, link in enumerate(book['download_links'], 1):
            print(f"  {i}. {link}")
    print(f"\n共获取 {len(books)} 本图书的下载链接")

    CTF_SUFFIX = ".ctfile.com"

    current_date = datetime.datetime.now().strftime("%m%d")
    SAVE_DIR = f"/home/user/Downloads/dushupai_books/{current_date}/"
    downloader = CTFileDownloader()

    if SAVE_DIR and not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)

    for book in books:
        for i, link in enumerate(book['download_links'], 1):
            parsed_url = urlparse(link)
            domain = parsed_url.netloc
            if not domain.endswith(CTF_SUFFIX):
                continue
            share_url = link
            # 替换share_url中Query参数pwd为p,即pwd=改为p=
            share_url = unquote(share_url)
            share_url = re.sub(r'pwd=', 'p=', share_url)

            print(f"\n处理图书 {book['title']} 下载链接 {share_url}")
            if downloader.download_from_share(share_url, SAVE_DIR, book['id']):
                print(f"\t 下载成功")
            else:
                print(f"\t 下载失败")

        time.sleep(3)  # 在下载之间添加延迟

    print("\n所有文件下载完成!")
