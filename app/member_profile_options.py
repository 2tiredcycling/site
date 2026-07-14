from __future__ import annotations

from datetime import date


ENTRY_YEAR_EARLIEST_BUCKET = 2022

GENDER_OPTIONS = (
    {"code": "男", "label": "男", "aliases": ("男", "male", "m")},
    {"code": "女", "label": "女", "aliases": ("女", "female", "f")},
)

SCHOOL_OPTIONS = (
    {"code": "SME", "label": "经管学院 | SME", "aliases": ("经管学院", "SME")},
    {"code": "SSE", "label": "理工学院 | SSE", "aliases": ("理工学院", "SSE")},
    {"code": "HSS", "label": "人文社科学院 | HSS", "aliases": ("人文社科学院", "HSS")},
    {"code": "SDS", "label": "数据科学学院 | SDS", "aliases": ("数据科学学院", "SDS")},
    {"code": "MED", "label": "医学院 | MED", "aliases": ("医学院", "MED")},
    {"code": "MUS", "label": "音乐学院 | School of Music", "aliases": ("音乐学院", "School of Music", "MUS")},
    {"code": "SPP", "label": "公共政策学院 | SPP", "aliases": ("公共政策学院", "SPP")},
    {"code": "SAI", "label": "人工智能学院 | SAI", "aliases": ("人工智能学院", "SAI")},
    {"code": "GS", "label": "研究生院 | GS", "aliases": ("研究生院", "GS")},
)

COLLEGE_OPTIONS = (
    {"code": "shaw", "label": "逸夫书院 | Shaw College", "aliases": ("逸夫书院", "Shaw College", "shaw")},
    {"code": "diligentia", "label": "学勤书院 | Diligentia College", "aliases": ("学勤书院", "Diligentia College", "diligentia")},
    {"code": "muse", "label": "思廷书院 | Muse College", "aliases": ("思廷书院", "Muse College", "muse")},
    {"code": "harmonia", "label": "祥波书院 | Harmonia College", "aliases": ("祥波书院", "Harmonia College", "harmonia")},
    {"code": "ling", "label": "道扬书院 | Ling College", "aliases": ("道扬书院", "Ling College", "ling")},
    {"code": "minerva", "label": "厚含书院 | Minerva College", "aliases": ("厚含书院", "Minerva College", "minerva")},
    {"code": "duan", "label": "永平书院 | Duan Family College", "aliases": ("永平书院", "Duan Family College", "duan")},
    {"code": "eighth", "label": "第八书院 | Eighth College", "aliases": ("第八书院", "Eighth College", "eighth")},
    {
        "code": "not_applicable",
        "label": "不适用 / 无书院 | Not applicable / Graduate student / No college",
        "aliases": (
            "不适用",
            "无书院",
            "研究生",
            "Not applicable",
            "Graduate student",
            "No college",
            "not_applicable",
        ),
    },
)


def _normalize_lookup_key(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _build_alias_map(options: tuple[dict, ...]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for option in options:
        code = option["code"]
        aliases[_normalize_lookup_key(code)] = code
        aliases[_normalize_lookup_key(option["label"])] = code
        for alias in option.get("aliases", ()):
            aliases[_normalize_lookup_key(alias)] = code
    return aliases


SCHOOL_ALIAS_MAP = _build_alias_map(SCHOOL_OPTIONS)
COLLEGE_ALIAS_MAP = _build_alias_map(COLLEGE_OPTIONS)
GENDER_ALIAS_MAP = _build_alias_map(GENDER_OPTIONS)


def normalize_gender(value: object) -> tuple[str | None, str]:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return None, ""
    if _normalize_lookup_key(raw) in {
        _normalize_lookup_key("不愿透露"),
        _normalize_lookup_key("不透露"),
        _normalize_lookup_key("保密"),
        _normalize_lookup_key("-"),
        _normalize_lookup_key("prefer not to say"),
        _normalize_lookup_key("none"),
    }:
        return None, ""
    code = GENDER_ALIAS_MAP.get(_normalize_lookup_key(raw))
    if not code:
        return None, "性别不在允许范围内。"
    return code, ""


def normalize_school(value: object) -> tuple[str | None, str]:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return None, ""
    code = SCHOOL_ALIAS_MAP.get(_normalize_lookup_key(raw))
    if not code:
        return None, "学院不在允许范围内。"
    return code, ""


def normalize_college(value: object) -> tuple[str | None, str]:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return None, ""
    code = COLLEGE_ALIAS_MAP.get(_normalize_lookup_key(raw))
    if not code:
        return None, "书院不在允许范围内。"
    return code, ""


def _display_option(value: object, options: tuple[dict, ...], alias_map: dict[str, str]) -> str:
    raw = " ".join(str(value or "").strip().split())
    if not raw:
        return ""
    code = alias_map.get(_normalize_lookup_key(raw), raw)
    for option in options:
        if option["code"] == code:
            return option["label"]
    return raw


def display_school(value: object) -> str:
    return _display_option(value, SCHOOL_OPTIONS, SCHOOL_ALIAS_MAP)


def display_college(value: object) -> str:
    return _display_option(value, COLLEGE_OPTIONS, COLLEGE_ALIAS_MAP)


def display_gender(value: object) -> str:
    normalized, error = normalize_gender(value)
    if error:
        return str(value or "").strip()
    return normalized or "-"


def current_entry_year_options(today: date | None = None) -> list[int]:
    current = today or date.today()
    latest_year = current.year if current.month >= 7 else current.year - 1
    latest_year = max(latest_year, ENTRY_YEAR_EARLIEST_BUCKET)
    return list(range(ENTRY_YEAR_EARLIEST_BUCKET, latest_year + 1))


def parse_entry_year(value: object) -> tuple[int | None, str]:
    if value is None or value == "":
        return None, ""
    if isinstance(value, float) and value.is_integer():
        return int(value), ""
    if isinstance(value, int):
        return value, ""
    raw = " ".join(str(value).strip().split())
    if not raw:
        return None, ""
    compact = raw.replace(" ", "")
    earliest_labels = {
        "2022级及以前",
        "2022级以前",
        "2022及以前",
        "2022以前",
        "2022andbefore",
        "before2023",
    }
    if compact.casefold() in {item.casefold() for item in earliest_labels}:
        return ENTRY_YEAR_EARLIEST_BUCKET, ""
    if compact.endswith("级"):
        compact = compact[:-1]
    try:
        return int(compact), ""
    except ValueError:
        return None, "入学年份需为数字，或填写 2022级及以前。"


def display_entry_year(value: object) -> str:
    year, error = parse_entry_year(value)
    if error or year is None:
        return ""
    if year <= ENTRY_YEAR_EARLIEST_BUCKET:
        return "2022级及以前"
    return f"{year}级"
