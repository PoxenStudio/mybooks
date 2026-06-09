import os
import requests
from bs4 import BeautifulSoup
import time
import datetime
from urllib.parse import parse_qs, urlparse
from ctfile_downloader import CTFileDownloader

MAX_PAGES = 3


def get_book_info(page, last_finished_book_ids, ignore_books):
    base_url = "https://www.iyd.wang"
    home_url = "https://www.iyd.wang"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    }

    book_data = []
    should_break = False  # 如果找到了已完成的书籍，则中止

    try:
        book_url = home_url if page == 1 else f"{home_url}/page/{page}/"
        print(f"正在处理第 {page} 页: {book_url}")
        home_response = requests.get(book_url, headers=headers, timeout=30)
        home_response.raise_for_status()
        home_soup = BeautifulSoup(home_response.text, 'html.parser')

        # 定位图书列表
        main_section = home_soup.find('main')
        if not main_section:
            print("未找到<main>标签")
            return book_data, should_break

        book_articles = main_section.find_all('article')
        if not book_articles:
            print("未找到图书条目")
            return book_data, should_break

        print(f"找到 {len(book_articles)} 本图书")

        # 遍历每本图书
        for idx, article in enumerate(book_articles):
            try:
                # 提取标题和详情页链接
                header = article.find('header')
                if not header:
                    continue

                h2 = header.find('h2')
                if not h2:
                    continue

                book_title = h2.get_text(strip=True)
                detail_link = h2.find('a')['href'] if h2.find('a') else None

                if not detail_link:
                    print(f"跳过 {book_title}: 无详情链接")
                    continue

                # 处理相对链接
                if not detail_link.startswith('http'):
                    detail_link = base_url + detail_link

                # 提取书籍ID - 从URL中提取ID号
                book_id = '0'
                try:
                    # 从URL中提取数字ID（如从https://www.iyd.wang/44904.html提取44904）
                    book_id = detail_link.split('/')[-1].split('.')[0]
                    # 确保这是一个数字ID
                    if not book_id.isdigit():
                        book_id = '0'
                except:
                    book_id = '0'

                if int(book_id) in ignore_books:
                    print(f"跳过 {book_title}: 忽略")
                    continue

                if int(book_id) in last_finished_book_ids:
                    print(f"跳过 {book_title}: 已完成")
                    should_break = True
                    break

                # 获取详情页内容
                time.sleep(1)  # 礼貌性延迟
                detail_response = requests.get(detail_link, headers=headers, timeout=10)
                detail_response.raise_for_status()
                detail_soup = BeautifulSoup(detail_response.text, 'html.parser')

                # 提取下载链接
                blockquote = detail_soup.find('blockquote')
                download_links = []

                if blockquote:
                    for link in blockquote.find_all('a', href=True):
                        original_link = link['href']
                        # 解析URL，提取url参数值
                        parsed_url = urlparse(original_link)
                        query_params = parse_qs(parsed_url.query)
                        if 'url' in query_params:
                            actual_url = query_params['url'][0]
                            download_links.append(actual_url)
                        else:
                            download_links.append(original_link)

                if download_links:
                    book_data.append({
                        "title": book_title,
                        "detail_url": detail_link,
                        "id": book_id,
                        "download_links": download_links
                    })
                    print(f"已处理 ({idx+1}/{len(book_articles)}): {book_title}")
                else:
                    print(f"跳过 {book_title}: 未找到下载链接")

            except Exception as e:
                print(f"处理图书时出错: {str(e)}")
                continue

    except Exception as e:
        print(f"主流程出错: {str(e)}")

    return book_data, should_break


if __name__ == "__main__":
    downloaded_books = {45472, 45488, 45468}
    ignore_books = {44856, 45181, 45465, 45439, 45419}

    books = []
    for page in range(MAX_PAGES):
        result, broken = get_book_info(page + 1, downloaded_books, ignore_books)
        if len(result) > 0:
            books.extend(result)

        if broken:
            print(f"在第 {page + 1} 页中止，已找到已完成的书籍")
            break

    print("\n最终结果:")
    for book in books:
        print(f"\n书名: {book['title']}")
        print(f"详情页: {book['detail_url']}")
        print("下载链接:")
        for i, link in enumerate(book['download_links'], 1):
            print(f"  {i}. {link}")

    if len(books) == 0:
        print("未找到任何图书信息")
        exit(0)

    print(f"\n共获取 {len(books)} 本图书的下载链接")

    CTF_SUFFIX = ".ctfile.com"

    current_date = datetime.datetime.now().strftime("%m%d")
    SAVE_DIR = f"/home/user/Downloads/iyd_wang_books/{current_date}/"
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
            print(f"\n处理图书 {book['title']} 下载链接 {link}")
            if downloader.download_from_share(link, SAVE_DIR, book['id']):
                print(f"\t 下载成功")
            else:
                print(f"\t 下载失败")

        time.sleep(3)  # 在下载之间添加延迟

    print("\n所有文件下载完成!")
