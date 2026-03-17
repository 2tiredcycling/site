import re

from app.auth import client_ip
from app.security_limits import consume_fixed_window

PROBE_PATH_PREFIXES = (
    "/wp-",
    "/wordpress",
    "/xmlrpc.php",
    "/phpmyadmin",
    "/pma",
    "/.git",
    "/.env",
    "/vendor",
    "/cgi-bin",
)
PROBE_PATH_EXACT = (
    "/.well-known/security.txt",
)
WATCHLIST_PROBE_PATHS = (
    "/wordpress/wp-admin/setup-config.php",
    "/wp-admin/setup-config.php",
    "/wp-login.php",
    "/xmlrpc.php",
    "/phpmyadmin",
    "/.env",
    "/.git/config",
)
PROBE_PATH_SUFFIXES = (
    ".php",
    ".asp",
    ".aspx",
    ".jsp",
    ".bak",
    ".sql",
    ".zip",
    ".tar.gz",
)
BOT_UA_KEYWORDS = (
    "bot",
    "spider",
    "crawler",
    "curl",
    "wget",
    "python-requests",
    "sqlmap",
    "nmap",
    "nikto",
)
_PATH_TRAVERSAL = re.compile(r"(?:\.\./|%2e%2e|%252e%252e)", re.IGNORECASE)
_ENCODED_DOTFILE = re.compile(r"%2e(?:git|env)", re.IGNORECASE)


def is_probe_path(path: str) -> bool:
    normalized = (path or "").strip().lower()
    if not normalized:
        return False
    if normalized in PROBE_PATH_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in PROBE_PATH_PREFIXES):
        return True
    if any(normalized.endswith(suffix) for suffix in PROBE_PATH_SUFFIXES):
        return True
    if _PATH_TRAVERSAL.search(normalized):
        return True
    if _ENCODED_DOTFILE.search(normalized):
        return True
    return False


def is_bot_user_agent(user_agent: str) -> bool:
    ua = (user_agent or "").strip().lower()
    if not ua:
        return False
    return any(token in ua for token in BOT_UA_KEYWORDS)


def is_probe_request(path: str, user_agent: str) -> bool:
    return is_probe_path(path) or is_bot_user_agent(user_agent)


def should_throttle_probe(path: str, user_agent: str) -> tuple[bool, int]:
    if not is_probe_request(path, user_agent):
        return True, 0
    return consume_fixed_window("probe_request", client_ip(), limit=120, window_seconds=60)


def is_watchlist_probe_path(path: str) -> bool:
    normalized = (path or "").strip().lower()
    if not normalized:
        return False
    if normalized in WATCHLIST_PROBE_PATHS:
        return True
    if normalized.startswith("/wordpress/wp-admin/"):
        return True
    return False


def build_non_probe_filters(model):
    filters = [~model.path.like("/manage%")]
    for prefix in PROBE_PATH_PREFIXES:
        filters.append(~model.path.like(f"{prefix}%"))
    for exact in PROBE_PATH_EXACT:
        filters.append(model.path != exact)
    for suffix in PROBE_PATH_SUFFIXES:
        filters.append(~model.path.like(f"%{suffix}"))
    return tuple(filters)
