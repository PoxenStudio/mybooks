"""
书源数据模型 — 兼容 Legado 3.0 JSON 子集

所有规则字段使用字符串表示选择器表达式，
空字符串表示该字段不启用。
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
import json


@dataclass
class RuleSearch:
    """搜索规则"""
    bookList: str = ""
    name: str = ""
    author: str = ""
    kind: str = ""
    wordCount: str = ""
    lastChapter: str = ""
    intro: str = ""
    coverUrl: str = ""
    bookUrl: str = ""
    init: str = ""


@dataclass
class RuleBookInfo:
    """书籍信息规则"""
    name: str = ""
    author: str = ""
    kind: str = ""
    wordCount: str = ""
    lastChapter: str = ""
    intro: str = ""
    coverUrl: str = ""
    tocUrl: str = ""
    init: str = ""


@dataclass
class RuleToc:
    """目录规则"""
    chapterList: str = ""
    chapterName: str = ""
    chapterUrl: str = ""
    isVolume: str = ""
    updateTime: str = ""
    init: str = ""
    nextTocUrl: str = ""


@dataclass
class ReplaceRule:
    """替换/净化规则"""
    pattern: str = ""
    replacement: str = ""
    isRegex: bool = False


@dataclass
class RuleContent:
    """正文规则"""
    content: str = ""
    nextContentUrl: str = ""
    webJs: str = ""
    sourceRegex: str = ""
    replaceRegex: list = field(default_factory=list)
    imageStyle: str = ""
    init: str = ""


def _keep_known_fields(cls, data: dict) -> dict:
    """只保留 dataclass 已声明的字段"""
    known = cls.__dataclass_fields__
    return {k: v for k, v in data.items() if k in known}


@dataclass
class BookSource:
    """书源 — 兼容 Legado 3.0 JSON 子集"""

    bookSourceName: str = ""
    bookSourceUrl: str = ""
    bookSourceGroup: str = ""
    bookSourceType: int = 0
    enabled: bool = True
    loginUrl: str = ""

    header: dict = field(default_factory=dict)

    ruleSearch: RuleSearch = field(default_factory=RuleSearch)
    ruleBookInfo: RuleBookInfo = field(default_factory=RuleBookInfo)
    ruleToc: RuleToc = field(default_factory=RuleToc)
    ruleContent: RuleContent = field(default_factory=RuleContent)

    exploreUrl: str = ""
    ruleExplore: dict = field(default_factory=dict)

    searchUrl: str = ""
    jsLib: str = ""

    weight: int = 0
    customOrder: int = 0
    lastUpdateTime: int = 0

    def to_dict(self) -> dict:
        result = {
            "bookSourceName": self.bookSourceName,
            "bookSourceUrl": self.bookSourceUrl,
            "bookSourceGroup": self.bookSourceGroup,
            "bookSourceType": self.bookSourceType,
            "enabled": self.enabled,
            "loginUrl": self.loginUrl,
            "header": self.header,
            "searchUrl": self.searchUrl,
            "jsLib": self.jsLib,
            "ruleSearch": asdict(self.ruleSearch),
            "ruleBookInfo": asdict(self.ruleBookInfo),
            "ruleToc": asdict(self.ruleToc),
            "ruleContent": _content_to_dict(self.ruleContent),
            "exploreUrl": self.exploreUrl,
            "ruleExplore": self.ruleExplore,
            "weight": self.weight,
            "customOrder": self.customOrder,
            "lastUpdateTime": self.lastUpdateTime,
        }
        return result

    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: dict) -> "BookSource":
        source = cls(
            bookSourceName=data.get("bookSourceName", ""),
            bookSourceUrl=data.get("bookSourceUrl", ""),
            bookSourceGroup=data.get("bookSourceGroup", ""),
            bookSourceType=data.get("bookSourceType", 0),
            enabled=data.get("enabled", True),
            loginUrl=data.get("loginUrl", ""),
            header=data.get("header", {}),
            searchUrl=data.get("searchUrl", ""),
            jsLib=data.get("jsLib", ""),
        )
        if "ruleSearch" in data and isinstance(data["ruleSearch"], dict):
            source.ruleSearch = RuleSearch(**_keep_known_fields(RuleSearch, data["ruleSearch"]))
        if "ruleBookInfo" in data and isinstance(data["ruleBookInfo"], dict):
            source.ruleBookInfo = RuleBookInfo(**_keep_known_fields(RuleBookInfo, data["ruleBookInfo"]))
        if "ruleToc" in data and isinstance(data["ruleToc"], dict):
            source.ruleToc = RuleToc(**_keep_known_fields(RuleToc, data["ruleToc"]))
        if "ruleContent" in data and isinstance(data["ruleContent"], dict):
            source.ruleContent = _content_from_dict(data["ruleContent"])
        source.exploreUrl = data.get("exploreUrl", "")
        source.ruleExplore = data.get("ruleExplore", {})
        source.weight = data.get("weight", 0)
        source.customOrder = data.get("customOrder", 0)
        source.lastUpdateTime = data.get("lastUpdateTime", 0)
        return source

    @classmethod
    def from_json(cls, text: str) -> "BookSource":
        return cls.from_dict(json.loads(text))


def _content_to_dict(rc: RuleContent) -> dict:
    d = asdict(rc)
    d["replaceRegex"] = [
        {"pattern": r.pattern, "replacement": r.replacement, "isRegex": r.isRegex}
        for r in rc.replaceRegex
    ]
    return d


def _content_from_dict(data: dict) -> RuleContent:
    rc = RuleContent(
        content=data.get("content", ""),
        nextContentUrl=data.get("nextContentUrl", ""),
        webJs=data.get("webJs", ""),
        sourceRegex=data.get("sourceRegex", ""),
        imageStyle=data.get("imageStyle", ""),
        init=data.get("init", ""),
    )
    raw = data.get("replaceRegex", [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                rc.replaceRegex.append(ReplaceRule(
                    pattern=item.get("pattern", ""),
                    replacement=item.get("replacement", ""),
                    isRegex=item.get("isRegex", False),
                ))
            elif isinstance(item, str):
                if "##" in item:
                    parts = item.split("##", 1)
                    rc.replaceRegex.append(ReplaceRule(
                        pattern=parts[0], replacement=parts[1], isRegex=True
                    ))
    return rc


def load_sources_from_json(path: str) -> list[BookSource]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return [BookSource.from_dict(item) for item in data]
    elif isinstance(data, dict):
        return [BookSource.from_dict(data)]
    raise ValueError("JSON 格式错误：需要数组或对象")


def dump_sources_to_json(sources: list[BookSource], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([s.to_dict() for s in sources], f, ensure_ascii=False, indent=2)
