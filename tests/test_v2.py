from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import AccessLog, Activity, Announcement, AuditLog, MediaAsset, ROLE_OPS_ADMIN, ROLE_VIEWER, Route, RouteFeedback, RouteVersion, SiteFeedback, User, db
from app.security_monitor import is_watchlist_probe_path


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf token not found"
    return match.group(1)


@pytest.fixture()
def app_and_client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("FLASK_ENV", "development")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("UPLOAD_FOLDER", str(upload_dir))
    monkeypatch.setenv("DEFAULT_ADMIN_USERNAME", "admin")
    monkeypatch.setenv("DEFAULT_ADMIN_PASSWORD", "admin123456789")
    monkeypatch.setenv("APP_DEPLOYED_AT", "2026-03-17T18:30:00+08:00")
    monkeypatch.setenv("ACCESS_LOG_ASYNC", "false")

    app = create_app()
    app.config.update(TESTING=True, SEED_DEMO_DATA=False)

    with app.test_client() as test_client:
        yield app, test_client


def login(client, username: str, password: str):
    login_page = client.get("/manage/login")
    token = _extract_csrf(login_page.get_data(as_text=True))
    return client.post(
        "/manage/login",
        data={"username": username, "password": password, "csrf_token": token},
        follow_redirects=True,
    )


def login_admin(client):
    return login(client, "admin", "admin123456789")


def get_manage_csrf(client) -> str:
    page = client.get("/manage")
    assert page.status_code == 200
    return _extract_csrf(page.get_data(as_text=True))


def create_route(client, csrf_token: str, name: str = "Test Route", follow_redirects: bool = True):
    gpx_content = b"<?xml version='1.0'?><gpx version='1.1'></gpx>"
    return client.post(
        "/manage/routes/create",
        data={
            "csrf_token": csrf_token,
            "route_name": name,
            "distance_km": "3.2",
            "difficulty": "easy",
            "category": "hiking",
            "description": "for test",
            "status": "published",
            "suggested_duration_hours": "1.5",
            "supply_points": "shop",
            "risk_warning": "slippery",
            "gpx_file": (BytesIO(gpx_content), f"{name}.gpx"),
        },
        content_type="multipart/form-data",
        follow_redirects=follow_redirects,
    )


def test_api_v1_list_available(app_and_client):
    _app, client = app_and_client
    resp = client.get("/api/v1/routes")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "items" in payload


def test_csrf_required_for_login(app_and_client):
    _app, client = app_and_client
    resp = client.post(
        "/manage/login",
        data={"username": "admin", "password": "admin123456789"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_unauth_manage_redirect_writes_audit_log(app_and_client):
    app, client = app_and_client
    resp = client.get("/manage", follow_redirects=False)
    assert resp.status_code == 302
    assert "/manage/login" in resp.headers.get("Location", "")

    with app.app_context():
        log = AuditLog.query.order_by(AuditLog.id.desc()).first()
        assert log is not None
        assert log.action == "auth.required_redirect"
        assert log.target_type == "admin"
        assert log.target_id == "/manage"
        assert '"path": "/manage"' in (log.detail or "")


def test_login_failed_writes_audit_log_with_ip(app_and_client):
    app, client = app_and_client
    login_page = client.get("/manage/login")
    token = _extract_csrf(login_page.get_data(as_text=True))
    resp = client.post(
        "/manage/login",
        data={"username": "admin", "password": "wrong-password", "csrf_token": token},
        headers={"X-Forwarded-For": "203.0.113.10"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        log = (
            AuditLog.query.filter_by(action="auth.login_failed")
            .order_by(AuditLog.id.desc())
            .first()
        )
        assert log is not None
        assert "ip=203.0.113.10" in (log.detail or "")


def test_access_log_persisted_for_web_request(app_and_client):
    app, client = app_and_client
    resp = client.get("/")
    assert resp.status_code == 200

    with app.app_context():
        log = (
            AccessLog.query.filter_by(path="/", method="GET")
            .order_by(AccessLog.id.desc())
            .first()
        )
        assert log is not None
        assert log.status_code == 200


def test_access_log_prefers_cf_connecting_ip(app_and_client):
    app, client = app_and_client
    resp = client.get("/", headers={"CF-Connecting-IP": "198.51.100.8", "X-Forwarded-For": "203.0.113.77"})
    assert resp.status_code == 200

    with app.app_context():
        log = (
            AccessLog.query.filter_by(path="/", method="GET")
            .order_by(AccessLog.id.desc())
            .first()
        )
        assert log is not None
        assert log.ip_address == "198.51.100.8"


def test_site_feedback_records_forwarded_ip(app_and_client):
    app, client = app_and_client
    resp = client.post(
        "/feedback",
        data={
            "category": "bug",
            "content": "这里有一个页面展示问题，麻烦排查。",
            "contact": "123456789",
            "source": "/",
        },
        headers={"X-Forwarded-For": "203.0.113.66"},
        follow_redirects=False,
    )
    assert resp.status_code == 302

    with app.app_context():
        entry = SiteFeedback.query.order_by(SiteFeedback.id.desc()).first()
        assert entry is not None
        assert entry.ip_address == "203.0.113.66"


def test_robots_txt_served(app_and_client):
    _app, client = app_and_client
    resp = client.get("/robots.txt")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "User-agent: *" in body
    assert "Disallow: /manage/" in body
    assert "Sitemap:" in body


def test_sitemap_xml_served(app_and_client):
    _app, client = app_and_client
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "<urlset" in body
    assert "/about" in body
    assert "/events" in body
    assert "/routes" in body


def test_v41_static_pages_available(app_and_client):
    _app, client = app_and_client
    assert client.get("/about").status_code == 200
    assert client.get("/team").status_code == 200
    assert client.get("/contact").status_code == 200
    assert client.get("/routes").status_code == 200


def test_events_alias_pages_available(app_and_client):
    app, client = app_and_client
    with app.app_context():
        activity = Activity(title="V4.1 Test Event")
        db.session.add(activity)
        db.session.commit()
        activity_id = activity.id

    list_resp = client.get("/events")
    assert list_resp.status_code == 200
    detail_resp = client.get(f"/events/{activity_id}")
    assert detail_resp.status_code == 200


def test_manage_announcements_crud(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)

    create_resp = client.post(
        "/manage/announcements/create",
        data={
            "csrf_token": csrf_token,
            "title": "Announcement A",
            "content": "公告内容 A",
            "status": "published",
            "is_pinned": "1",
            "sort_order": "8",
            "published_at": "2026-03-20T12:00",
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200

    with app.app_context():
        item = Announcement.query.filter_by(title="Announcement A").first()
        assert item is not None
        assert item.is_pinned is True
        assert item.status == "published"
        announcement_id = item.id

    edit_page = client.get(f"/manage/announcements/{announcement_id}/edit")
    assert edit_page.status_code == 200

    update_resp = client.post(
        f"/manage/announcements/{announcement_id}/update",
        data={
            "csrf_token": csrf_token,
            "title": "Announcement B",
            "content": "公告内容 B",
            "status": "offline",
            "is_pinned": "0",
            "sort_order": "2",
            "published_at": "",
        },
        follow_redirects=True,
    )
    assert update_resp.status_code == 200

    with app.app_context():
        item = db.session.get(Announcement, announcement_id)
        assert item is not None
        assert item.title == "Announcement B"
        assert item.status == "offline"
        assert item.is_pinned is False

    list_resp = client.get("/manage/announcements")
    assert list_resp.status_code == 200
    assert "Announcement B" in list_resp.get_data(as_text=True)

    delete_resp = client.post(
        f"/manage/announcements/{announcement_id}/delete",
        data={"csrf_token": csrf_token},
        follow_redirects=True,
    )
    assert delete_resp.status_code == 200
    with app.app_context():
        assert db.session.get(Announcement, announcement_id) is None


def test_route_detail_back_link_from_activity_detail(app_and_client):
    app, client = app_and_client
    with app.app_context():
        route = Route(
            route_name="Back Link Route",
            gpx_filename="back_link_route.gpx",
            status="published",
            is_deleted=False,
        )
        activity = Activity(title="Back Link Event")
        activity.routes.append(route)
        db.session.add_all([route, activity])
        db.session.commit()
        route_id = route.id
        activity_id = activity.id

    resp = client.get(f"/routes/{route_id}?from_activity_id={activity_id}&from_detail=web.events_detail")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "返回活动详情" in body
    assert f"/events/{activity_id}" in body


def test_activity_media_upload_and_render(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)

    png_bytes = b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x02\\x00\\x00\\x00\\x90wS\\xde\\x00\\x00\\x00\\x0cIDATx\\x9cc``\\x00\\x00\\x00\\x04\\x00\\x01\\x0b\\xe7\\x02\\x9d\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82"
    mp4_bytes = b"\\x00\\x00\\x00\\x18ftypmp42\\x00\\x00\\x00\\x00mp42isom"

    resp = client.post(
        "/manage/activities/create",
        data={
            "csrf_token": csrf_token,
            "title": "Media Event",
            "activity_time": "2026-03-20T10:00",
            "participant_count": "15",
            "weather": "sunny",
            "summary": "with media",
            "media_files": [
                (BytesIO(png_bytes), "photo.png"),
                (BytesIO(mp4_bytes), "clip.mp4"),
            ],
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        activity = Activity.query.filter_by(title="Media Event").first()
        assert activity is not None
        assets = MediaAsset.query.filter_by(activity_id=activity.id).all()
        assert len(assets) >= 2
        first_asset_id = assets[0].id
        activity_id = activity.id

    media_resp = client.get(f"/media/{first_asset_id}")
    assert media_resp.status_code == 200

    detail_resp = client.get(f"/events/{activity_id}")
    body = detail_resp.get_data(as_text=True)
    assert detail_resp.status_code == 200
    assert "/media/" in body


def test_probe_wordpress_path_blocked_early(app_and_client):
    app, client = app_and_client
    resp = client.get("/wordpress/wp-admin/setup-config.php")
    assert resp.status_code == 404

    with app.app_context():
        log = (
            AccessLog.query.filter_by(path="/wordpress/wp-admin/setup-config.php")
            .order_by(AccessLog.id.desc())
            .first()
        )
        assert log is not None
        assert log.status_code == 404


def test_watchlist_probe_path_match():
    assert is_watchlist_probe_path("/wordpress/wp-admin/setup-config.php")
    assert is_watchlist_probe_path("/wp-login.php")
    assert not is_watchlist_probe_path("/routes/1")


def test_404_page_is_lightweight(app_and_client):
    _app, client = app_and_client
    resp = client.get("/not-found-anymore")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 404
    assert "返回首页" in text
    assert "查找路线" not in text


def test_manage_analytics_page_available_after_login(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage/analytics")
    assert resp.status_code == 200
    assert "流量统计" in resp.get_data(as_text=True)
    assert "近5分钟活跃(估算)" not in resp.get_data(as_text=True)


def test_manage_analytics_excludes_self_path(app_and_client):
    app, client = app_and_client
    with app.app_context():
        db.session.add(
            AccessLog(
                path="/manage/analytics",
                method="GET",
                endpoint="admin.analytics_page",
                status_code=200,
                ip_address="203.0.113.1",
                user_agent="pytest",
                referer="",
            )
        )
        db.session.add(
            AccessLog(
                path="/manage/routes",
                method="GET",
                endpoint="admin.routes_page",
                status_code=200,
                ip_address="203.0.113.9",
                user_agent="pytest",
                referer="",
            )
        )
        db.session.add(
            AccessLog(
                path="/",
                method="GET",
                endpoint="web.index",
                status_code=200,
                ip_address="203.0.113.2",
                user_agent="pytest",
                referer="",
            )
        )
        db.session.commit()

    assert login_admin(client).status_code == 200
    resp = client.get("/manage/analytics?days=1")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "<td>/manage/analytics</td>" not in text
    assert "<td>/manage/routes</td>" not in text
    assert "<td>/</td>" in text


def test_manage_analytics_supports_post_deploy_scope(app_and_client):
    app, client = app_and_client
    with app.app_context():
        baseline_utc = datetime.fromisoformat("2026-03-17T18:30:00+08:00").astimezone(timezone.utc)
        db.session.add(
            AccessLog(
                path="/",
                method="GET",
                endpoint="web.index",
                status_code=200,
                ip_address="203.0.113.3",
                user_agent="pytest",
                referer="",
                created_at=baseline_utc - timedelta(hours=1),
            )
        )
        db.session.add(
            AccessLog(
                path="/",
                method="GET",
                endpoint="web.index",
                status_code=200,
                ip_address="203.0.113.4",
                user_agent="pytest",
                referer="",
                created_at=baseline_utc + timedelta(hours=1),
            )
        )
        db.session.commit()

    assert login_admin(client).status_code == 200
    resp = client.get("/manage/analytics?scope=post_deploy")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "上线后（" in text
    assert "业务PV" in text


def test_manage_analytics_shows_probe_excluded_metrics(app_and_client):
    app, client = app_and_client
    with app.app_context():
        db.session.add(
            AccessLog(
                path="/",
                method="GET",
                endpoint="web.index",
                status_code=200,
                ip_address="203.0.113.20",
                user_agent="pytest",
                referer="",
            )
        )
        db.session.add(
            AccessLog(
                path="/wp-login.php",
                method="GET",
                endpoint="",
                status_code=404,
                ip_address="203.0.113.21",
                user_agent="pytest",
                referer="",
            )
        )
        db.session.commit()

    assert login_admin(client).status_code == 200
    resp = client.get("/manage/analytics?days=1")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "排除探测" in text
    assert "探测占比" in text


def test_manage_dashboard_shows_active_5m_metric(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage")
    assert resp.status_code == 200
    assert "近5分钟活跃(估算)" in resp.get_data(as_text=True)


def test_manage_dashboard_shows_security_entry(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "安全监控" in text
    assert "当前版本：v3.3.2" in text


def test_manage_security_page_available_after_login(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage/security")
    assert resp.status_code == 200
    text = resp.get_data(as_text=True)
    assert "核心安全指标" in text
    assert "最近安全事件" in text


def test_manage_security_supports_post_deploy_scope(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage/security?scope=post_deploy")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "核心安全指标（上线后（" in text


def test_manage_security_events_filter_and_pagination(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    resp = client.get("/manage/security?event_type=watchlist&event_status=5xx&event_q=wp-admin&event_page=1")
    text = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "事件类型" in text
    assert "状态码" in text
    assert "第 " in text


def test_admin_login_and_create_route(app_and_client):
    _app, client = app_and_client
    login_resp = login_admin(client)
    assert login_resp.status_code == 200

    csrf_token = get_manage_csrf(client)
    resp = create_route(client, csrf_token, name="Test Route")
    assert resp.status_code == 200

    list_resp = client.get("/api/v1/routes")
    items = list_resp.get_json()["items"]
    assert any(item["route_name"] == "Test Route" for item in items)


def test_download_updates_stats(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200

    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Stats Route")

    list_resp = client.get("/api/v1/routes")
    route_id = list_resp.get_json()["items"][0]["id"]

    scanner_resp = client.get(f"/download/{route_id}")
    assert scanner_resp.status_code == 200
    detail_before = client.get(f"/api/v1/routes/{route_id}").get_json()
    assert detail_before["download_count"] in (0, None)

    tracked_resp = client.post(f"/download/{route_id}/track")
    assert tracked_resp.status_code == 200

    detail = client.get(f"/api/v1/routes/{route_id}").get_json()
    assert detail["download_count"] >= 1
    assert detail["last_downloaded_at"] is not None


def test_viewer_cannot_create_route(app_and_client):
    app, client = app_and_client
    with app.app_context():
        if not User.query.filter_by(username="viewer").first():
            viewer = User(
                username="viewer",
                password=generate_password_hash("viewer123456789"),
                role=ROLE_VIEWER,
                is_active=True,
            )
            db.session.add(viewer)
            db.session.commit()

    login(client, "viewer", "viewer123456789")
    csrf_token = get_manage_csrf(client)

    resp = create_route(client, csrf_token, name="Should Fail", follow_redirects=False)
    assert resp.status_code in (302, 403)

    check = client.get("/api/v1/routes").get_json()["items"]
    assert all(item["route_name"] != "Should Fail" for item in check)


def test_user_with_manage_users_permission_can_open_users_page(app_and_client):
    app, client = app_and_client
    with app.app_context():
        manager = User(
            username="manager",
            password=generate_password_hash("manager123456789"),
            role=ROLE_VIEWER,
            is_active=True,
            perm_manage_users=True,
            perm_view_analytics=True,
        )
        db.session.add(manager)
        db.session.commit()

    login(client, "manager", "manager123456789")
    resp = client.get("/manage/users")
    assert resp.status_code == 200
    assert "账号列表" in resp.get_data(as_text=True)


def test_user_without_analytics_permission_forbidden(app_and_client):
    app, client = app_and_client
    with app.app_context():
        blocked = User(
            username="blocked_user",
            password=generate_password_hash("blocked123456789"),
            role=ROLE_VIEWER,
            is_active=True,
            perm_view_analytics=False,
        )
        db.session.add(blocked)
        db.session.commit()

    login(client, "blocked_user", "blocked123456789")
    resp = client.get("/manage/analytics")
    assert resp.status_code == 302
    assert "/manage/login" in (resp.headers.get("Location") or "")


def test_dashboard_hides_sections_without_permissions(app_and_client):
    app, client = app_and_client
    with app.app_context():
        viewer = User(
            username="limited_viewer",
            password=generate_password_hash("viewer123456789"),
            role=ROLE_VIEWER,
            is_active=True,
            perm_view_analytics=False,
            perm_view_security=False,
            perm_review=False,
            perm_edit_content=False,
            perm_manage_users=False,
            perm_view_audit_logs=False,
        )
        db.session.add(viewer)
        db.session.commit()

    login(client, "limited_viewer", "viewer123456789")
    resp = client.get("/manage")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "流量统计" not in body
    assert "安全监控" not in body
    assert "最新审计日志" not in body
    assert "管理员账号" not in body


def test_user_without_edit_or_review_cannot_download_import_report(app_and_client):
    app, client = app_and_client
    with app.app_context():
        viewer = User(
            username="report_blocked",
            password=generate_password_hash("viewer123456789"),
            role=ROLE_VIEWER,
            is_active=True,
            perm_edit_content=False,
            perm_review=False,
        )
        db.session.add(viewer)
        db.session.commit()

    login(client, "report_blocked", "viewer123456789")
    resp = client.get("/manage/import-report/any-token")
    assert resp.status_code == 302
    assert "/manage/login" in (resp.headers.get("Location") or "")


def test_bulk_import_invalid_csv_does_not_leave_uploaded_files(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200

    csrf_token = get_manage_csrf(client)
    upload_dir = app.config["UPLOAD_FOLDER"]
    before = {p.name for p in Path(upload_dir).glob("*.gpx")}

    bad_csv = "bad,header\n1,2\n".encode("utf-8")
    gpx_content = b"<?xml version='1.0'?><gpx version='1.1'></gpx>"
    resp = client.post(
        "/manage/bulk-import",
        data={
            "csrf_token": csrf_token,
            "csv_file": (BytesIO(bad_csv), "bad.csv"),
            "gpx_files": (BytesIO(gpx_content), "bulk_orphan.gpx"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert resp.status_code == 200

    after = {p.name for p in Path(upload_dir).glob("*.gpx")}
    assert after == before


def test_feedback_review_flow(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Feedback Route")

    route_id = client.get("/api/v1/routes").get_json()["items"][0]["id"]

    feedback_resp = client.post(
        f"/api/v1/routes/{route_id}/feedback",
        json={
            "rating": 4,
            "comment": "路况良好",
            "road_condition_update": "中段有施工",
            "report_type": "changed",
        },
    )
    assert feedback_resp.status_code == 201
    feedback_id = feedback_resp.get_json()["id"]

    with app.app_context():
        reviewer = User(
            username="reviewer",
            password=generate_password_hash("reviewer123456789"),
            role=ROLE_OPS_ADMIN,
            is_active=True,
            perm_review=True,
        )
        db.session.add(reviewer)
        db.session.commit()
    admin_csrf = get_manage_csrf(client)
    forged_resp = client.post(
        f"/api/v1/admin/feedback/{feedback_id}/review",
        headers={"X-Admin-User": "99999", "X-CSRF-Token": admin_csrf},
        json={"status": "approved", "reviewer_note": "forged"},
    )
    assert forged_resp.status_code == 403
    assert forged_resp.get_json()["error"] == "admin_user_mismatch"

    client.post("/manage/logout", data={"csrf_token": admin_csrf}, follow_redirects=True)
    assert login(client, "reviewer", "reviewer123456789").status_code == 200
    reviewer_csrf = get_manage_csrf(client)

    review_resp = client.post(
        f"/api/v1/admin/feedback/{feedback_id}/review",
        headers={"X-CSRF-Token": reviewer_csrf},
        json={"status": "approved", "reviewer_note": "已核实"},
    )
    assert review_resp.status_code == 200
    assert review_resp.get_json()["status"] == "approved"

    with app.app_context():
        feedback = db.session.get(RouteFeedback, feedback_id)
        assert feedback is not None
        assert feedback.status == "approved"


def test_route_version_rollback(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Rollback Route")

    with app.app_context():
        route = Route.query.filter_by(route_name="Rollback Route").first()
        assert route is not None
        route_id = route.id

    csrf_token = get_manage_csrf(client)
    update_resp = client.post(
        f"/manage/routes/{route_id}/update",
        data={
            "csrf_token": csrf_token,
            "route_name": "Rollback Route v2",
            "distance_km": "8",
            "difficulty": "hard",
            "category": "hiking",
            "description": "updated",
            "status": "published",
            "suggested_duration_hours": "4",
            "supply_points": "none",
            "risk_warning": "heat",
        },
        follow_redirects=True,
    )
    assert update_resp.status_code == 200

    with app.app_context():
        versions = (
            RouteVersion.query.filter_by(route_id=route_id)
            .order_by(RouteVersion.version_no.asc())
            .all()
        )
        assert len(versions) >= 2
        first_version = versions[0].version_no

    csrf_token = get_manage_csrf(client)
    rollback_resp = client.post(
        f"/manage/routes/{route_id}/rollback",
        data={"csrf_token": csrf_token, "version_no": str(first_version)},
        follow_redirects=True,
    )
    assert rollback_resp.status_code == 200

    with app.app_context():
        route = db.session.get(Route, route_id)
        assert route is not None
        assert route.route_name == "Rollback Route"


def test_route_rollback_rejects_missing_gpx_snapshot(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Rollback Missing GPX")

    with app.app_context():
        route = Route.query.filter_by(route_name="Rollback Missing GPX").first()
        assert route is not None
        route_id = route.id
        first_version = (
            RouteVersion.query.filter_by(route_id=route_id)
            .order_by(RouteVersion.version_no.asc())
            .first()
        )
        assert first_version is not None
        payload = json.loads(first_version.snapshot_json)
        payload["gpx_filename"] = "not_exists_rollback.gpx"
        first_version.snapshot_json = json.dumps(payload, ensure_ascii=False)
        db.session.commit()
        old_name = route.route_name

    csrf_token = get_manage_csrf(client)
    rollback_resp = client.post(
        f"/manage/routes/{route_id}/rollback",
        data={"csrf_token": csrf_token, "version_no": "1"},
        follow_redirects=True,
    )
    assert rollback_resp.status_code == 200

    with app.app_context():
        route = db.session.get(Route, route_id)
        assert route is not None
        assert route.route_name == old_name


