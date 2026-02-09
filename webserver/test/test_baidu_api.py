import logging
import os
import sys
from webserver.plugins.meta.baike.api import BaiduBaikeApi

# Setup Calibre paths
path = os.environ.get('CALIBRE_PYTHON_PATH', '/usr/lib/calibre')
if path not in sys.path:
    sys.path.insert(0, path)

sys.resources_location = os.environ.get('CALIBRE_RESOURCES_PATH', '/usr/share/calibre')
sys.extensions_location = os.environ.get('CALIBRE_EXTENSIONS_PATH', '/usr/lib/calibre/calibre/plugins')
sys.executables_location = os.environ.get('CALIBRE_EXECUTABLES_PATH', '/usr/bin')

logging.basicConfig(level=logging.DEBUG)


def test_baike_api():
    print("Testing Baidu Baike API...")
    api = BaiduBaikeApi()
    data = api.get_book(u"3100_宛平南路600号：我做精神科医生的60年")
    print(data)
    print(data.website)
    print(data.cover_url)
    print(data.tags)
    # Write cover data to temp file for verification
    if data.cover_data:
        img_fmt, img_data = data.cover_data
        with open(f"test_cover.{img_fmt}", "wb") as f:
            f.write(img_data)
        print(f"Cover image saved as test_cover.{img_fmt}")


if __name__ == "__main__":
    test_baike_api()
