"""
工具管理类，所有工具进行注册

@author: shiningsprk-arch, 2026
"""


class Tool:
    def __init__(self, id: str, name: str, description: str, revision: str, author: str, publish_date: str = "", page: str = "", repo_url: str = ""):
        self._id = id
        self._name = name
        self._description = description
        self._revision = revision
        self._author = author
        self._publish_date = publish_date
        self._page = page
        # 工具源码仓库地址，供审核/溯源使用，见 document/Toolbox_Dynamic_Design.md 3.2 节。
        # 外部插件的 manifest.json 里是必填字段；14 个内置工具尚未逐个补充，暂时允许为空，
        # 不在 ToolSet.register() 里强制校验，避免一次性改动全部内置工具的 info()。
        self._repo_url = repo_url

    @property
    def id(self) -> str:
        return self._id

    @id.setter
    def id(self, value: str):
        self._id = value

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def description(self) -> str:
        return self._description

    @description.setter
    def description(self, value: str):
        self._description = value

    @property
    def revision(self) -> str:
        return self._revision

    @revision.setter
    def revision(self, value: str):
        self._revision = value

    @property
    def author(self) -> str:
        return self._author

    @author.setter
    def author(self, value: str):
        self._author = value

    @property
    def publish_date(self) -> str:
        return self._publish_date

    @publish_date.setter
    def publish_date(self, value: str):
        self._publish_date = value

    @property
    def page(self) -> str:
        return self._page

    @page.setter
    def page(self, value: str):
        self._page = value

    @property
    def repo_url(self) -> str:
        return self._repo_url

    @repo_url.setter
    def repo_url(self, value: str):
        self._repo_url = value

    def to_dict(self) -> dict:
        return {
            "id": self._id,
            "name": self._name,
            "description": self._description,
            "revision": self._revision,
            "author": self._author,
            "publish_date": self._publish_date,
            "page": self._page,
            "repo_url": self._repo_url,
        }


class ToolSet:
    _tool_set: dict[str, Tool] = {}

    @staticmethod
    def collect_tools():
        from .rare_book_downloader import RareBookDownloader
        from .merge_formats_tool import MergeFormatsTool
        from .review_book_language_tool import ReviewBookLanguageTool
        from .minify_pdf import MinifyPdfTool
        from .text_processor import TextProcessor
        from .formats_pruning import FormatsPruningTool
        from .epub_fixer import EpubFixerTool
        from .epub_split import EpubSplitTool
        from .author_clean_tool import AuthorCleanTool
        from .mimo_tts import MimoTTSTool
        from .bookbarn_acceptor_tool import BookBarnAcceptorTool
        from .text_replace import TextReplaceTool
        from .txt_encoding_fixer import TxtEncodingFixerTool
        from .chinese_converter_tool import ChineseConverterTool
        from .epub_beautify import EpubBeautifyTool

        ToolSet.register(MergeFormatsTool.info())
        ToolSet.register(EpubBeautifyTool.info())
        ToolSet.register(MimoTTSTool.info())
        ToolSet.register(TextReplaceTool.info())
        ToolSet.register(TxtEncodingFixerTool.info())
        ToolSet.register(ChineseConverterTool.info())
        ToolSet.register(TextProcessor.info())
        ToolSet.register(FormatsPruningTool.info())
        ToolSet.register(EpubSplitTool.info())
        ToolSet.register(AuthorCleanTool.info())
        ToolSet.register(RareBookDownloader.info())
        ToolSet.register(ReviewBookLanguageTool.info())
        ToolSet.register(EpubFixerTool.info())
        ToolSet.register(MinifyPdfTool.info())
        ToolSet.register(BookBarnAcceptorTool.info())

        MinifyPdfTool.cleanup_old_files()

    @staticmethod
    def register(info: dict):
        required = ("tool_id", "name", "description", "revision", "author")
        if not all(k in info for k in required):
            raise ValueError("Tool info must contain 'tool_id', 'name', 'description', 'revision', and 'author'")
        tool = Tool(
            id=info["tool_id"],
            name=info["name"],
            description=info["description"],
            revision=info["revision"],
            author=info["author"],
            publish_date=info.get("publish_date", ""),
            page=info.get("page", ""),
            repo_url=info.get("repo_url", ""),
        )
        ToolSet._tool_set[info["tool_id"]] = tool

    @staticmethod
    def unregister(tool_id: str) -> None:
        ToolSet._tool_set.pop(tool_id, None)

    @staticmethod
    def all_tools() -> list[Tool]:
        return list(ToolSet._tool_set.values())

    @staticmethod
    def get_tool(tool_id: str) -> Tool | None:
        return ToolSet._tool_set.get(tool_id)
