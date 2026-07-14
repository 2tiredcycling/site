from __future__ import annotations


CURRENT_MEMBERSHIP_APPLICATION_FORM_VERSION = 1

APPLICATION_STATUS_PENDING = "pending"
APPLICATION_STATUS_APPROVED = "approved"
APPLICATION_STATUS_REJECTED = "rejected"
APPLICATION_STATUS_OPTIONS = (
    {"code": APPLICATION_STATUS_PENDING, "label": "待审核"},
    {"code": APPLICATION_STATUS_APPROVED, "label": "已通过"},
    {"code": APPLICATION_STATUS_REJECTED, "label": "已拒绝"},
)
APPLICATION_STATUSES = tuple(option["code"] for option in APPLICATION_STATUS_OPTIONS)

COMPETITION_INTEREST_YES = "yes"
COMPETITION_INTEREST_NO = "no"
COMPETITION_INTEREST_UNSURE = "unsure"
COMPETITION_INTEREST_OPTIONS = (
    {"code": COMPETITION_INTEREST_YES, "label": "愿意参加比赛"},
    {"code": COMPETITION_INTEREST_NO, "label": "暂不考虑"},
    {"code": COMPETITION_INTEREST_UNSURE, "label": "还不确定"},
)
COMPETITION_INTEREST_VALUES = tuple(option["code"] for option in COMPETITION_INTEREST_OPTIONS)

CYCLING_EXPERIENCE_BEGINNER = "beginner"
CYCLING_EXPERIENCE_CASUAL = "casual"
CYCLING_EXPERIENCE_LONG_DISTANCE = "long_distance"
CYCLING_EXPERIENCE_COMPETITION = "competition"
CYCLING_EXPERIENCE_OPTIONS = (
    {"code": CYCLING_EXPERIENCE_BEGINNER, "label": "几乎没有骑行经验"},
    {"code": CYCLING_EXPERIENCE_CASUAL, "label": "偶尔休闲骑行"},
    {"code": CYCLING_EXPERIENCE_LONG_DISTANCE, "label": "有中长途骑行经验"},
    {"code": CYCLING_EXPERIENCE_COMPETITION, "label": "有比赛经验"},
)
CYCLING_EXPERIENCE_VALUES = tuple(option["code"] for option in CYCLING_EXPERIENCE_OPTIONS)

BICYCLE_STATUS_NO_BICYCLE = "no_bicycle"
BICYCLE_STATUS_MOUNTAIN_BIKE = "mountain_bike"
BICYCLE_STATUS_ROAD_BIKE = "road_bike"
BICYCLE_STATUS_FOLDING_COMMUTER = "folding_commuter"
BICYCLE_STATUS_OTHER_BICYCLE = "other_bicycle"
BICYCLE_STATUS_OFF_CAMPUS = "off_campus"
BICYCLE_STATUS_OPTIONS = (
    {"code": BICYCLE_STATUS_NO_BICYCLE, "label": "暂无自行车"},
    {"code": BICYCLE_STATUS_MOUNTAIN_BIKE, "label": "有山地车"},
    {"code": BICYCLE_STATUS_ROAD_BIKE, "label": "有公路车"},
    {"code": BICYCLE_STATUS_FOLDING_COMMUTER, "label": "有折叠车或通勤车"},
    {"code": BICYCLE_STATUS_OTHER_BICYCLE, "label": "有其他类型自行车"},
    {"code": BICYCLE_STATUS_OFF_CAMPUS, "label": "有车但不在校内"},
)
BICYCLE_STATUS_VALUES = tuple(option["code"] for option in BICYCLE_STATUS_OPTIONS)


def _label_for(options: tuple[dict, ...], value: str | None) -> str:
    for option in options:
        if option["code"] == value:
            return option["label"]
    return value or ""


def application_status_label(value: str | None) -> str:
    return _label_for(APPLICATION_STATUS_OPTIONS, value)


def competition_interest_label(value: str | None) -> str:
    return _label_for(COMPETITION_INTEREST_OPTIONS, value)


def cycling_experience_label(value: str | None) -> str:
    return _label_for(CYCLING_EXPERIENCE_OPTIONS, value)


def bicycle_status_label(value: str | None) -> str:
    return _label_for(BICYCLE_STATUS_OPTIONS, value)


def is_valid_application_status(value: str | None) -> bool:
    return value in APPLICATION_STATUSES


def is_valid_competition_interest(value: str | None) -> bool:
    return value in COMPETITION_INTEREST_VALUES


def is_valid_cycling_experience(value: str | None) -> bool:
    return value in CYCLING_EXPERIENCE_VALUES


def is_valid_bicycle_status(value: str | None) -> bool:
    return value in BICYCLE_STATUS_VALUES
