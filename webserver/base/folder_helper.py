import re

from webserver.constants import CALIBRE_COLUMN_FOLDER

FOLDER_SEP = "."
MAX_DEPTH = 2
MAX_SEGMENT_LEN = 24
CLEAR_WORDS = ("清除", "clear")
_SEGMENT_RE = re.compile(r"^[^\W_]+$")


def normalize_segment(name):
    name = (name or "").strip()
    if not name or len(name) > MAX_SEGMENT_LEN or not _SEGMENT_RE.match(name):
        raise ValueError("invalid folder name")
    return name


def split_folder(value):
    value = (value or "").strip()
    return value.split(FOLDER_SEP) if value else []


def normalize_folder(raw):
    """Validate a folder path and return it; empty (or a clear word) means root."""
    raw = (raw or "").strip()
    if not raw or raw.lower() in CLEAR_WORDS:
        return ""
    parts = raw.split(FOLDER_SEP)
    if len(parts) > MAX_DEPTH:
        raise ValueError("folder too deep")
    return FOLDER_SEP.join(normalize_segment(p) for p in parts)


def folder_table(cache):
    """Return Calibre's in-memory table of #folder, or None if the column is missing."""
    field = cache.fields.get(CALIBRE_COLUMN_FOLDER)
    return field.table if field is not None else None


def folder_counts(cache):
    """Return {folder value: number of books directly in it}."""
    table = folder_table(cache)
    if table is None:
        return {}
    return {v: len(table.col_book_map.get(i, ())) for i, v in table.id_map.items()}


def top_level_count(counts):
    return len({split_folder(v)[0] for v, n in counts.items() if v and n > 0})


def build_tree(counts):
    """Build [{name, count, children}] from direct counts; count includes sub-folders."""
    top = {}
    for value, n in counts.items():
        parts = split_folder(value)
        if not parts or n <= 0:
            continue
        node = top.setdefault(parts[0], {"name": parts[0], "count": 0, "children": {}})
        node["count"] += n
        if len(parts) > 1:
            child = node["children"].setdefault(parts[1], {"name": parts[1], "count": 0})
            child["count"] += n
    return [
        {"name": n["name"], "count": n["count"], "children": sorted(n["children"].values(), key=lambda c: c["name"])}
        for n in sorted(top.values(), key=lambda n: n["name"])
    ]


def plan_rename(values, path, name):
    """Return {old value: new value} for path and its sub-folders after renaming its last segment."""
    parts = path.split(FOLDER_SEP)
    new_path = FOLDER_SEP.join(parts[:-1] + [name])
    plan = {}
    for v in values:
        if v == path or v.startswith(path + FOLDER_SEP):
            plan[v] = new_path + v[len(path):]
    return plan
