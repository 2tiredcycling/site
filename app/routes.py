from datetime import datetime, timezone
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.utils import secure_filename

from app.models import Route, db

bp = Blueprint("main", __name__)


@bp.get("/")
def index() -> str:
    routes = (
        Route.query.filter_by(is_active=True)
        .order_by(Route.created_at.desc())
        .all()
    )
    return render_template("index.html", routes=routes)


@bp.get("/manage")
def manage() -> str:
    auth_redirect = _require_manage_auth()
    if auth_redirect:
        return auth_redirect
    message = request.args.get("message")
    level = request.args.get("level", "info")
    routes = (
        Route.query.filter_by(is_active=True)
        .order_by(Route.created_at.desc())
        .all()
    )
    return render_template("manage.html", routes=routes, message=message, level=level)


@bp.get("/manage/login")
def manage_login():
    if session.get("manage_authed"):
        return redirect(url_for("main.manage"))
    message = request.args.get("message")
    return render_template("manage_login.html", message=message)


@bp.post("/manage/login")
def manage_login_submit():
    password = (request.form.get("password") or "").strip()
    expected = current_app.config.get("ADMIN_PASSWORD", "")
    if not expected or password != expected:
        current_app.logger.warning("manage_login_failed ip=%s", request.remote_addr)
        return redirect(url_for("main.manage_login", message="密码错误"))
    session["manage_authed"] = True
    current_app.logger.info("manage_login_success ip=%s", request.remote_addr)
    return redirect(url_for("main.manage", message="已进入编辑界面", level="success"))


@bp.post("/manage/logout")
def manage_logout():
    session.pop("manage_authed", None)
    return redirect(url_for("main.manage_login", message="已退出编辑界面"))


@bp.post("/manage/create")
def create_route():
    auth_redirect = _require_manage_auth()
    if auth_redirect:
        return auth_redirect
    route_name = (request.form.get("route_name") or "").strip()
    distance_raw = (request.form.get("distance_km") or "").strip()
    gpx_file = request.files.get("gpx_file")

    if not route_name:
        return _redirect_manage_with_message("路线名称不能为空", "error")
    if not distance_raw:
        return _redirect_manage_with_message("里程数不能为空", "error")
    if not gpx_file or not gpx_file.filename:
        return _redirect_manage_with_message("请上传 GPX 文件", "error")

    distance_km = _parse_distance(distance_raw)
    if distance_km is None:
        return _redirect_manage_with_message("里程数必须是大于等于 0 的数字", "error")

    safe_name = secure_filename(gpx_file.filename)
    if not safe_name.lower().endswith(".gpx"):
        return _redirect_manage_with_message("仅支持 .gpx 文件", "error")

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    save_name = _next_available_filename(upload_folder, safe_name)
    save_path = upload_folder / save_name

    try:
        gpx_file.save(save_path)
        route = Route(
            route_name=route_name,
            gpx_filename=save_name,
            created_at=datetime.now(timezone.utc),
            uploaded_at=datetime.now(timezone.utc),
            distance_km=distance_km,
            is_active=True,
        )
        db.session.add(route)
        db.session.commit()
    except Exception:
        if save_path.exists():
            save_path.unlink(missing_ok=True)
        db.session.rollback()
        current_app.logger.exception("create_route_failed")
        return _redirect_manage_with_message("新增失败，请稍后重试", "error")

    current_app.logger.info("create_route_success route_name=%s filename=%s", route_name, save_name)
    return _redirect_manage_with_message("新增成功", "success")


@bp.post("/manage/<int:route_id>/update")
def update_route(route_id: int):
    auth_redirect = _require_manage_auth()
    if auth_redirect:
        return auth_redirect
    route = Route.query.filter_by(id=route_id, is_active=True).first()
    if not route:
        return _redirect_manage_with_message("路线不存在", "error")

    route_name = (request.form.get("route_name") or "").strip()
    distance_raw = (request.form.get("distance_km") or "").strip()
    gpx_file = request.files.get("gpx_file")

    if not route_name:
        return _redirect_manage_with_message("路线名称不能为空", "error")
    if not distance_raw:
        return _redirect_manage_with_message("里程数不能为空", "error")

    distance_km = _parse_distance(distance_raw)
    if distance_km is None:
        return _redirect_manage_with_message("里程数必须是大于等于 0 的数字", "error")

    old_filename = route.gpx_filename
    new_filename = old_filename
    new_file_path = None
    if gpx_file and gpx_file.filename:
        safe_name = secure_filename(gpx_file.filename)
        if not safe_name.lower().endswith(".gpx"):
            return _redirect_manage_with_message("仅支持 .gpx 文件", "error")
        upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
        new_filename = _next_available_filename(upload_folder, safe_name)
        new_file_path = upload_folder / new_filename
        gpx_file.save(new_file_path)

    try:
        route.route_name = route_name
        route.uploaded_at = datetime.now(timezone.utc)
        route.distance_km = distance_km
        route.gpx_filename = new_filename
        db.session.commit()
    except Exception:
        db.session.rollback()
        if new_file_path and new_file_path.exists():
            new_file_path.unlink(missing_ok=True)
        current_app.logger.exception("update_route_failed route_id=%s", route_id)
        return _redirect_manage_with_message("修改失败，请稍后重试", "error")

    if new_filename != old_filename:
        old_path = Path(current_app.config["UPLOAD_FOLDER"]) / old_filename
        try:
            old_path.unlink(missing_ok=True)
        except OSError:
            current_app.logger.warning("old_file_remove_failed route_id=%s filename=%s", route_id, old_filename)
    current_app.logger.info("update_route_success route_id=%s", route_id)
    return _redirect_manage_with_message("修改成功", "success")


@bp.post("/manage/<int:route_id>/delete")
def delete_route(route_id: int):
    auth_redirect = _require_manage_auth()
    if auth_redirect:
        return auth_redirect
    route = Route.query.filter_by(id=route_id, is_active=True).first()
    if not route:
        return _redirect_manage_with_message("路线不存在或已删除", "error")

    file_name = route.gpx_filename
    try:
        db.session.delete(route)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception("delete_route_failed route_id=%s", route_id)
        return _redirect_manage_with_message("删除失败，请稍后重试", "error")

    file_path = Path(current_app.config["UPLOAD_FOLDER"]) / file_name
    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        current_app.logger.warning("file_remove_failed route_id=%s filename=%s", route_id, file_name)
    current_app.logger.info("delete_route_success route_id=%s filename=%s", route_id, file_name)
    return _redirect_manage_with_message("删除成功", "success")


@bp.get("/download/<int:route_id>")
def download(route_id: int):
    route = Route.query.filter_by(id=route_id, is_active=True).first()
    if not route:
        current_app.logger.warning("download_failed reason=route_not_found route_id=%s", route_id)
        abort(404, description="路线不存在")

    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    file_path = upload_folder / route.gpx_filename
    if not file_path.exists():
        current_app.logger.warning(
            "download_failed reason=file_missing route_id=%s filename=%s",
            route_id,
            route.gpx_filename,
        )
        abort(404, description="GPX 文件不存在")

    current_app.logger.info("download_success route_id=%s filename=%s", route_id, route.gpx_filename)
    return send_from_directory(
        directory=str(upload_folder),
        path=route.gpx_filename,
        as_attachment=True,
        download_name=route.gpx_filename,
        mimetype="application/gpx+xml",
    )


@bp.get("/api/routes")
def api_routes():
    routes = (
        Route.query.filter_by(is_active=True)
        .order_by(Route.created_at.desc())
        .all()
    )
    return jsonify([item.as_dict() for item in routes])


@bp.get("/health")
def health() -> Response:
    return Response("ok", mimetype="text/plain")


@bp.app_errorhandler(404)
def handle_404(error):
    routes = (
        Route.query.filter_by(is_active=True)
        .order_by(Route.created_at.desc())
        .all()
    )
    message = getattr(error, "description", "资源不存在")
    return render_template("index.html", routes=routes, error_message=message), 404


def _next_available_filename(upload_folder: Path, source_name: str) -> str:
    stem = Path(source_name).stem
    suffix = Path(source_name).suffix
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate = f"{stamp}_{source_name}"
    counter = 1
    while (upload_folder / candidate).exists() or Route.query.filter_by(gpx_filename=candidate).first():
        candidate = f"{stamp}_{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def _redirect_manage_with_message(message: str, level: str):
    return redirect(url_for("main.manage", message=message, level=level))


def _parse_distance(value: str):
    try:
        distance = float(value)
    except ValueError:
        return None
    if distance < 0:
        return None
    return distance


def _require_manage_auth():
    if session.get("manage_authed"):
        return None
    return redirect(url_for("main.manage_login", message="请先输入管理密码"))
