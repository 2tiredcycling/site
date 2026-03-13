from datetime import timedelta

from app.models import RateLimitState, db, utcnow


def _now():
    return utcnow()


def _get_or_create_state(action: str, subject: str) -> RateLimitState:
    state = RateLimitState.query.filter_by(action=action, subject=subject).first()
    if state:
        return state
    state = RateLimitState(action=action, subject=subject, window_started_at=_now(), count=0)
    db.session.add(state)
    db.session.flush()
    return state


def _seconds_left(target_time) -> int:
    if not target_time:
        return 0
    remaining = int((target_time - _now()).total_seconds())
    return max(0, remaining)


def _reset_window_if_needed(state: RateLimitState, window_seconds: int) -> None:
    if window_seconds <= 0:
        return
    elapsed = (_now() - state.window_started_at).total_seconds()
    if elapsed >= window_seconds:
        state.window_started_at = _now()
        state.count = 0
        state.locked_until = None


def check_lock(action: str, subject: str, window_seconds: int) -> int:
    state = RateLimitState.query.filter_by(action=action, subject=subject).first()
    if not state:
        return 0
    _reset_window_if_needed(state, window_seconds)
    retry_after = _seconds_left(state.locked_until)
    if retry_after == 0 and state.locked_until is not None:
        state.locked_until = None
        db.session.commit()
    return retry_after


def register_failure(action: str, subject: str, max_attempts: int, window_seconds: int, lock_seconds: int) -> int:
    state = _get_or_create_state(action, subject)
    _reset_window_if_needed(state, window_seconds)
    if _seconds_left(state.locked_until) > 0:
        db.session.commit()
        return _seconds_left(state.locked_until)

    state.count += 1
    retry_after = 0
    if state.count >= max_attempts:
        state.locked_until = _now() + timedelta(seconds=max(1, lock_seconds))
        retry_after = _seconds_left(state.locked_until)
    db.session.commit()
    return retry_after


def clear_state(action: str, subject: str) -> None:
    state = RateLimitState.query.filter_by(action=action, subject=subject).first()
    if not state:
        return
    db.session.delete(state)
    db.session.commit()


def consume_fixed_window(action: str, subject: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    state = _get_or_create_state(action, subject)
    _reset_window_if_needed(state, window_seconds)

    if state.count >= limit:
        retry_after = _seconds_left(state.window_started_at + timedelta(seconds=window_seconds))
        db.session.commit()
        return False, max(1, retry_after)

    state.count += 1
    db.session.commit()
    return True, 0
