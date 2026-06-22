from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import re

import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import AccessLog, Activity, ActivityRouteOption, Announcement, AuditLog, MediaAsset, MERCH_BATCH_ACTIVE, MERCH_BATCH_ENDED, MERCH_BATCH_UPCOMING, MERCH_ORDER_CANCELLED, MERCH_ORDER_PENDING, MerchPreorderBatch, MerchPreorderRegistration, ROLE_OPS_ADMIN, ROLE_VIEWER, Route, RouteFeedback, RouteVersion, SiteFeedback, User, db
from app.security_monitor import is_watchlist_probe_path


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf token not found"
    return match.group(1)


def _project_version() -> str:
    return Path("VERSION").read_text(encoding="utf-8-sig").strip()


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


def create_route(
    client,
    csrf_token: str,
    name: str = "Test Route",
    follow_redirects: bool = True,
    distance_km: str = "3.2",
    gpx_content: bytes | None = None,
):
    if gpx_content is None:
        gpx_content = b"<?xml version='1.0'?><gpx version='1.1'></gpx>"
    return client.post(
        "/manage/routes/create",
        data={
            "csrf_token": csrf_token,
            "route_name": name,
            "distance_km": distance_km,
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
    home = client.get("/")
    assert home.status_code == 200
    home_body = home.get_data(as_text=True)
    assert "骑行服预定" in home_body
    assert "/kit" in home_body
    assert client.get("/about").status_code == 200
    assert client.get("/team").status_code == 404
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


def test_kit_preorder_submit_update_lookup_and_cancel(app_and_client):
    app, client = app_and_client
    deadline = datetime.now(timezone.utc) + timedelta(days=7)
    with app.app_context():
        batch = MerchPreorderBatch(
            title="Kit Batch A",
            status=MERCH_BATCH_ACTIVE,
            deadline_at=deadline,
            description="This overview description should stay hidden",
            price_min=180,
            price_max=220,
            is_visible=True,
        )
        db.session.add(batch)
        db.session.commit()
        batch_id = batch.id

    detail = client.get(f"/kit/{batch_id}")
    assert detail.status_code == 200
    assert "Kit Batch A" in detail.get_data(as_text=True)
    list_resp = client.get("/kit")
    assert list_resp.status_code == 200
    assert "This overview description should stay hidden" not in list_resp.get_data(as_text=True)

    submit_resp = client.post(
        f"/kit/{batch_id}/submit",
        data={
            "name": "Alice",
            "student_id": "123456",
            "phone": "13800000000",
            "gender": "女",
            "size": "L",
            "quantity": "1",
            "notes": "first",
        },
        follow_redirects=False,
    )
    assert submit_resp.status_code == 302
    assert f"/kit/{batch_id}/success" in submit_resp.headers.get("Location", "")

    check_resp = client.get(f"/kit/{batch_id}/check-student?student_id=123456")
    assert check_resp.status_code == 200
    assert check_resp.get_json()["exists"] is True
    registration_id = check_resp.get_json()["registration_id"]

    update_resp = client.post(
        f"/kit/{batch_id}/submit",
        data={
            "name": "Alice",
            "student_id": "123456",
            "phone": "13800000001",
            "gender": "女",
            "size": "XL",
            "quantity": "2",
            "notes": "updated",
            "update_registration_id": str(registration_id),
        },
        follow_redirects=False,
    )
    assert update_resp.status_code == 302

    with app.app_context():
        rows = MerchPreorderRegistration.query.filter_by(batch_id=batch_id).all()
        assert len(rows) == 1
        assert rows[0].size == "XL"
        assert rows[0].quantity == 2

    lookup = client.get(f"/kit/{batch_id}/lookup?name=Alice&student_id=123456")
    assert lookup.status_code == 200
    body = lookup.get_data(as_text=True)
    assert "XL" in body
    assert "取消预报名" in body

    cancel_resp = client.post(
        f"/kit/{batch_id}/cancel",
        data={"name": "Alice", "student_id": "123456"},
        follow_redirects=False,
    )
    assert cancel_resp.status_code == 302
    with app.app_context():
        row = MerchPreorderRegistration.query.filter_by(batch_id=batch_id).first()
        assert row is not None
        assert row.status == MERCH_ORDER_CANCELLED


def test_manage_kit_preorder_create_and_registrations_page(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    manage_page = client.get("/manage")
    assert manage_page.status_code == 200
    assert f"当前版本：{_project_version()}" in manage_page.get_data(as_text=True)
    new_page = client.get("/manage/kit-preorders/new")
    assert new_page.status_code == 200
    new_page_body = new_page.get_data(as_text=True)
    assert 'name="status"' not in new_page_body
    assert 'name="start_date"' in new_page_body
    assert 'name="deadline_date"' in new_page_body

    csrf_token = get_manage_csrf(client)
    resp = client.post(
        "/manage/kit-preorders/create",
        data={
            "csrf_token": csrf_token,
            "title": "Managed Kit Batch",
            "start_date": "2026-12-01",
            "deadline_date": "2026-12-31",
            "price_min": "180",
            "price_max": "220",
            "price_note": "最终价格按人数确认",
            "size_note": "尺码偏小，建议买大一码。",
            "description": "后台创建测试",
            "is_visible": "1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert "Managed Kit Batch" in resp.get_data(as_text=True)

    with app.app_context():
        batch = MerchPreorderBatch.query.filter_by(title="Managed Kit Batch").first()
        assert batch is not None
        assert batch.status == MERCH_BATCH_UPCOMING
        assert batch.start_at is not None
        assert batch.deadline_at is not None
        assert batch.deadline_at.minute == 59
        batch_id = batch.id
        db.session.add(
            MerchPreorderRegistration(
                batch_id=batch_id,
                name="Bob",
                student_id="654321",
                phone="13900000000",
                gender="男",
                size="M",
                quantity=1,
                status=MERCH_ORDER_PENDING,
            )
        )
        db.session.commit()

    list_resp = client.get("/manage/kit-preorders")
    assert list_resp.status_code == 200
    assert "Managed Kit Batch" in list_resp.get_data(as_text=True)

    registrations_resp = client.get(f"/manage/kit-preorders/{batch_id}/registrations")
    assert registrations_resp.status_code == 200
    text = registrations_resp.get_data(as_text=True)
    assert "Bob" in text
    assert "654321" in text


def test_ended_kit_preorder_only_allows_lookup(app_and_client):
    app, client = app_and_client
    deadline = datetime.now(timezone.utc) - timedelta(days=1)
    with app.app_context():
        batch = MerchPreorderBatch(
            title="Ended Kit Batch",
            status=MERCH_BATCH_ENDED,
            deadline_at=deadline,
            is_visible=True,
        )
        db.session.add(batch)
        db.session.flush()
        registration = MerchPreorderRegistration(
            batch_id=batch.id,
            name="Ended User",
            student_id="20260001",
            phone="13800000002",
            gender="男",
            size="L",
            quantity=1,
            status=MERCH_ORDER_PENDING,
        )
        db.session.add(registration)
        db.session.commit()
        batch_id = batch.id

    lookup = client.get(f"/kit/{batch_id}/lookup?name=Ended+User&student_id=20260001")
    body = lookup.get_data(as_text=True)
    assert lookup.status_code == 200
    assert "查询预报名" in body
    assert "取消预报名" not in body

    cancel_resp = client.post(
        f"/kit/{batch_id}/cancel",
        data={"name": "Ended User", "student_id": "20260001"},
        follow_redirects=False,
    )
    assert cancel_resp.status_code == 302
    with app.app_context():
        row = MerchPreorderRegistration.query.filter_by(batch_id=batch_id).first()
        assert row is not None
        assert row.status == MERCH_ORDER_PENDING


def test_global_kit_preorder_lookup_lists_all_visible_records(app_and_client):
    app, client = app_and_client
    active_deadline = datetime.now(timezone.utc) + timedelta(days=7)
    ended_deadline = datetime.now(timezone.utc) - timedelta(days=1)
    with app.app_context():
        active_batch = MerchPreorderBatch(
            title="Global Active Batch",
            status=MERCH_BATCH_ACTIVE,
            deadline_at=active_deadline,
            is_visible=True,
        )
        ended_batch = MerchPreorderBatch(
            title="Global Ended Batch",
            status=MERCH_BATCH_ENDED,
            deadline_at=ended_deadline,
            is_visible=True,
        )
        hidden_batch = MerchPreorderBatch(
            title="Global Hidden Batch",
            status=MERCH_BATCH_ACTIVE,
            deadline_at=active_deadline,
            is_visible=False,
        )
        db.session.add_all([active_batch, ended_batch, hidden_batch])
        db.session.flush()
        db.session.add_all(
            [
                MerchPreorderRegistration(
                    batch_id=active_batch.id,
                    name="Global User",
                    student_id="20260002",
                    phone="13800000003",
                    gender="女",
                    size="M",
                    quantity=1,
                    status=MERCH_ORDER_PENDING,
                ),
                MerchPreorderRegistration(
                    batch_id=ended_batch.id,
                    name="Global User",
                    student_id="20260002",
                    phone="13800000003",
                    gender="女",
                    size="L",
                    quantity=2,
                    status=MERCH_ORDER_PENDING,
                ),
                MerchPreorderRegistration(
                    batch_id=hidden_batch.id,
                    name="Global User",
                    student_id="20260002",
                    phone="13800000003",
                    gender="女",
                    size="XL",
                    quantity=1,
                    status=MERCH_ORDER_PENDING,
                ),
            ]
        )
        db.session.commit()
        active_batch_id = active_batch.id

    lookup = client.get("/kit/lookup?name=Global+User&student_id=20260002")
    body = lookup.get_data(as_text=True)
    assert lookup.status_code == 200
    assert "Global Active Batch" in body
    assert "Global Ended Batch" in body
    assert "Global Hidden Batch" not in body
    assert body.count("取消预报名") == 1

    cancel_resp = client.post(
        f"/kit/{active_batch_id}/cancel",
        data={"name": "Global User", "student_id": "20260002", "source": "global"},
        follow_redirects=False,
    )
    assert cancel_resp.status_code == 302
    assert "/kit/lookup" in cancel_resp.headers.get("Location", "")
    with app.app_context():
        active_row = MerchPreorderRegistration.query.filter_by(batch_id=active_batch_id).first()
        assert active_row is not None
        assert active_row.status == MERCH_ORDER_CANCELLED


def test_upcoming_kit_preorder_hides_lookup_entry(app_and_client):
    app, client = app_and_client
    start_at = datetime.now(timezone.utc) + timedelta(days=3)
    deadline = datetime.now(timezone.utc) + timedelta(days=7)
    with app.app_context():
        batch = MerchPreorderBatch(
            title="Upcoming Kit Batch",
            status=MERCH_BATCH_UPCOMING,
            start_at=start_at,
            deadline_at=deadline,
            is_visible=True,
        )
        db.session.add(batch)
        db.session.commit()
        batch_id = batch.id

    list_resp = client.get("/kit")
    assert list_resp.status_code == 200
    body = list_resp.get_data(as_text=True)
    assert "Upcoming Kit Batch" in body
    assert f"/kit/{batch_id}/lookup" not in body

    detail_resp = client.get(f"/kit/{batch_id}")
    assert detail_resp.status_code == 200
    detail_body = detail_resp.get_data(as_text=True)
    assert "查询/取消预报名" not in detail_body
    assert "查询预报名" not in detail_body


def test_manage_announcements_crud(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    with app.app_context():
        linked_route = Route(route_name="Announcement Route", gpx_filename="announcement_route.gpx", status="published")
        linked_activity = Activity(title="Announcement Activity")
        db.session.add_all([linked_route, linked_activity])
        db.session.commit()
        linked_route_id = linked_route.id
        linked_activity_id = linked_activity.id

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
            "offline_at": "2026-03-25T12:00",
            "activity_ids": [str(linked_activity_id)],
            "route_ids": [str(linked_route_id)],
        },
        follow_redirects=True,
    )
    assert create_resp.status_code == 200

    with app.app_context():
        item = Announcement.query.filter_by(title="Announcement A").first()
        assert item is not None
        assert item.is_pinned is True
        assert item.status == "published"
        assert len(item.activities) == 1
        assert len(item.routes) == 1
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
            "offline_at": "",
            "activity_ids": [],
            "route_ids": [],
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
        assert len(item.activities) == 0
        assert len(item.routes) == 0

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


def test_announcement_detail_visibility_and_associations(app_and_client):
    app, client = app_and_client
    now = datetime.now(timezone.utc)
    with app.app_context():
        route = Route(route_name="Ann Detail Route", gpx_filename="ann_detail_route.gpx", status="published")
        activity = Activity(title="Ann Detail Activity")
        announcement = Announcement(
            title="Ann Detail",
            content="公告详情正文",
            status="published",
            published_at=now - timedelta(hours=1),
            offline_at=now + timedelta(days=1),
        )
        announcement.routes.append(route)
        announcement.activities.append(activity)
        db.session.add_all([route, activity, announcement])
        db.session.commit()
        announcement_id = announcement.id

    detail = client.get(f"/announcements/{announcement_id}")
    body = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "Ann Detail" in body
    assert "Ann Detail Route" in body
    assert "Ann Detail Activity" in body


def test_announcement_schedule_blocks_future_or_expired(app_and_client):
    app, client = app_and_client
    now = datetime.now(timezone.utc)
    with app.app_context():
        future_item = Announcement(
            title="Future Ann",
            content="not yet",
            status="published",
            published_at=now + timedelta(days=1),
        )
        expired_item = Announcement(
            title="Expired Ann",
            content="expired",
            status="published",
            published_at=now - timedelta(days=2),
            offline_at=now - timedelta(days=1),
        )
        db.session.add_all([future_item, expired_item])
        db.session.commit()
        future_id = future_item.id
        expired_id = expired_item.id

    assert client.get(f"/announcements/{future_id}").status_code == 404
    assert client.get(f"/announcements/{expired_id}").status_code == 404
    index_body = client.get("/").get_data(as_text=True)
    assert "Future Ann" not in index_body
    assert "Expired Ann" not in index_body


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


def test_activity_route_options_saved_and_rendered(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Tier Route A")
    create_route(client, csrf_token, name="Tier Route B")
    create_route(client, csrf_token, name="Tier Route C")
    routes = client.get("/api/v1/routes").get_json()["items"]
    route_ids = [item["id"] for item in routes[:3]]

    resp = client.post(
        "/manage/activities/create",
        data={
            "csrf_token": csrf_token,
            "title": "Tier Activity",
            "activity_date": "2026-03-21",
            "route_option_beginner": str(route_ids[0]),
            "route_option_beginner_time": "09:00",
            "route_option_beginner_participants": "12",
            "route_option_intermediate": str(route_ids[1]),
            "route_option_intermediate_time": "09:30",
            "route_option_intermediate_participants": "8",
            "route_option_advanced": str(route_ids[2]),
            "route_option_advanced_time": "10:00",
            "route_option_advanced_participants": "5",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200

    with app.app_context():
        activity = Activity.query.filter_by(title="Tier Activity").first()
        assert activity is not None
        options = ActivityRouteOption.query.filter_by(activity_id=activity.id).all()
        assert len(options) == 3
        assert len(activity.routes) >= 3
        assert sum(item.participant_count for item in options) == 25
        sh_tz = timezone(timedelta(hours=8))
        option_times = {
            item.level_key: item.activity_time.replace(tzinfo=timezone.utc).astimezone(sh_tz).strftime("%Y-%m-%d %H:%M")
            for item in options
        }
        assert option_times["beginner"] == "2026-03-21 09:00"
        assert option_times["intermediate"] == "2026-03-21 09:30"
        assert option_times["advanced"] == "2026-03-21 10:00"
        assert activity.activity_time.replace(tzinfo=timezone.utc).astimezone(sh_tz).strftime("%Y-%m-%d %H:%M") == "2026-03-21 09:00"
        activity_id = activity.id

    detail = client.get(f"/events/{activity_id}")
    body = detail.get_data(as_text=True)
    assert detail.status_code == 200
    assert "初级路线" in body
    assert "中级路线" in body
    assert "高级路线" in body
    assert "参与人数" in body


def test_activity_detail_legacy_route_relation_compatible(app_and_client):
    app, client = app_and_client
    with app.app_context():
        route = Route(
            route_name="Legacy Activity Route",
            gpx_filename="legacy_activity_route.gpx",
            status="published",
            is_deleted=False,
            distance_km=12.3,
        )
        activity = Activity(title="Legacy Activity Detail")
        activity.routes.append(route)
        db.session.add_all([route, activity])
        db.session.commit()
        activity_id = activity.id

    resp = client.get(f"/events/{activity_id}")
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "初级路线" in body
    assert "Legacy Activity Route" in body


def test_activity_media_upload_and_render(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    create_route(client, csrf_token, name="Media Route")
    route_id = client.get("/api/v1/routes").get_json()["items"][0]["id"]

    png_bytes = b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01\\x08\\x02\\x00\\x00\\x00\\x90wS\\xde\\x00\\x00\\x00\\x0cIDATx\\x9cc``\\x00\\x00\\x00\\x04\\x00\\x01\\x0b\\xe7\\x02\\x9d\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82"
    mp4_bytes = b"\\x00\\x00\\x00\\x18ftypmp42\\x00\\x00\\x00\\x00mp42isom"

    resp = client.post(
        "/manage/activities/create",
        data={
            "csrf_token": csrf_token,
            "title": "Media Event",
            "route_option_beginner": str(route_id),
            "route_option_beginner_time": "2026-03-20T10:00",
            "route_option_beginner_participants": "15",
            "media_files_beginner": [
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
    assert f"当前版本：{_project_version()}" in text


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


def test_route_distance_and_elevation_stats_auto_computed_from_gpx(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)

    # ~111m straight line with elevation gain.
    gpx_content = b"""<?xml version='1.0' encoding='UTF-8'?>
<gpx version='1.1' creator='pytest'>
  <trk><name>Auto Stats</name><trkseg>
    <trkpt lat='22.500000' lon='114.100000'><ele>10</ele></trkpt>
    <trkpt lat='22.501000' lon='114.100000'><ele>24</ele></trkpt>
  </trkseg></trk>
</gpx>"""
    resp = create_route(
        client,
        csrf_token,
        name="Auto Stats Route",
        distance_km="999.9",
        gpx_content=gpx_content,
    )
    assert resp.status_code == 200

    with app.app_context():
        route = Route.query.filter_by(route_name="Auto Stats Route").first()
        assert route is not None
        assert route.distance_km != 999.9
        assert route.distance_km > 0
        assert route.ascent_m is not None
        assert route.max_ele_m is not None


def test_recalculate_route_stats_endpoint_refreshes_saved_values(app_and_client):
    app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)

    gpx_content = b"""<?xml version='1.0' encoding='UTF-8'?>
<gpx version='1.1' creator='pytest'>
  <trk><name>Recalc Stats</name><trkseg>
    <trkpt lat='22.500000' lon='114.100000'><ele>18</ele></trkpt>
    <trkpt lat='22.501000' lon='114.100000'><ele>31</ele></trkpt>
  </trkseg></trk>
</gpx>"""
    create_route(client, csrf_token, name="Recalc Stats Route", gpx_content=gpx_content)

    with app.app_context():
        route = Route.query.filter_by(route_name="Recalc Stats Route").first()
        assert route is not None
        route_id = route.id
        upload_dir = Path(app.config["UPLOAD_FOLDER"])
        original_path = upload_dir / route.gpx_filename
        fallback_name = "Recalc_Stats_Route.gpx"
        (upload_dir / fallback_name).write_bytes(original_path.read_bytes())
        route.gpx_filename = f"20260101000000_{fallback_name}"
        route.distance_km = 0.0
        route.ascent_m = 0.0
        route.descent_m = 0.0
        route.suggested_duration_hours = 99.0
        db.session.commit()

    csrf_token = get_manage_csrf(client)
    resp = client.post(
        f"/manage/routes/{route_id}/recalculate-stats",
        data={
            "csrf_token": csrf_token,
            "difficulty": "5",
            "manual_distance_km": "12.5",
            "manual_ascent_m": "100",
        },
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["stats"]["distance_km"] > 0

    with app.app_context():
        route = db.session.get(Route, route_id)
        assert route is not None
        assert route.distance_km == 12.5
        assert route.ascent_m == 100
        assert '"distance_km": 12.5' in route.manual_stat_overrides
        expected_duration = round((12.5 / 25 + 100 / 600) * 1.15, 1)
        assert route.suggested_duration_hours == expected_duration


def test_route_preview_returns_waypoints_from_gpx(app_and_client):
    _app, client = app_and_client
    assert login_admin(client).status_code == 200
    csrf_token = get_manage_csrf(client)
    gpx_content = b"""<?xml version='1.0' encoding='UTF-8'?>
<gpx version='1.1' creator='pytest'>
  <wpt lat='22.7423' lon='114.2882'>
    <name>\xe7\xae\xa1\xe5\x88\xb6\xe5\x8c\xba\xe5\x9f\x9f</name>
    <cmt>\xe7\xbb\x95\xe8\xa1\x8c</cmt>
    <desc>\xe7\xbb\x95\xe8\xa1\x8c</desc>
    <type>risk:high</type>
    <sym>Restricted Area</sym>
  </wpt>
  <wpt lat='22.7424' lon='114.2884'>
    <name>\xe6\x8f\x90\xe9\x86\x92\xe7\x82\xb9</name>
    <desc>\xe6\xb3\xa8\xe6\x84\x8f\xe6\xa8\xaa\xe9\xa3\x8e</desc>
    <type>low</type>
  </wpt>
  <trk><trkseg>
    <trkpt lat='22.500000' lon='114.100000'><ele>18</ele></trkpt>
    <trkpt lat='22.501000' lon='114.100000'><ele>31</ele></trkpt>
  </trkseg></trk>
</gpx>"""
    create_route(client, csrf_token, name="Waypoint Route", gpx_content=gpx_content)
    route_id = client.get("/api/v1/routes").get_json()["items"][0]["id"]
    resp = client.get(f"/api/v1/routes/{route_id}/preview")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert "waypoints" in payload
    assert len(payload["waypoints"]) == 2
    assert payload["waypoints"][0]["kind"] == "risk"
    assert payload["waypoints"][0]["risk_level"] == "high"
    assert payload["waypoints"][1]["risk_level"] == "low"


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


