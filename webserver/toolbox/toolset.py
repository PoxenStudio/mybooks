"""
工具管理类，所有工具进行注册
"""


class Tool:
    def __init__(self, id: str, name: str, description: str, revision: str, author: str, publish_date: str = "", page: str = ""):
        self._id = id
        self._name = name
        self._description = description
        self._revision = revision
        self._author = author
        self._publish_date = publish_date
        self._page = page

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

    def to_dict(self) -> dict:
        return {
            "id": self._id,
            "name": self._name,
            "description": self._description,
            "revision": self._revision,
            "author": self._author,
            "publish_date": self._publish_date,
            "page": self._page,
        }


class ToolSet:
    _tool_set: dict[str, Tool] = {}

    @staticmethod
    def collect_tools():
        from .rare_book_downloader import RareBookDownloader
        from .merge_formats_tool import MergeFormatsTool
        from .review_cht_books_tool import ReviewTraditionalChineseTool
        from .minify_pdf import MinifyPdfTool
        ToolSet.register(RareBookDownloader.info())
        ToolSet.register(MergeFormatsTool.info())
        ToolSet.register(ReviewTraditionalChineseTool.info())
        ToolSet.register(MinifyPdfTool.info())
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
            page=info.get("page", "")
        )
        ToolSet._tool_set[info["tool_id"]] = tool

    @staticmethod
    def all_tools() -> list[Tool]:
        return list(ToolSet._tool_set.values())

    @staticmethod
    def get_tool(tool_id: str) -> Tool | None:
        return ToolSet._tool_set.get(tool_id)
