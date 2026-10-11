"""Sentry for the backend: errors, request traces, and a record of every Gemma call.

Everything here is a no-op until SENTRY_DSN is set in .env, so the app (and
the tests) run exactly the same without Sentry.

What you get in Sentry (https://sentry.io) once it's on:
  - Issues: unhandled errors, plus one event per quest that FAILED to generate
    (all attempts gave unusable answers / Gemma timed out) with every attempt,
    its rejection reasons, timing and tokens attached.
  - Traces (Performance / AI Agents insights): POST /users/{id}/quests ->
    "quest.generate" span -> one "gen_ai.chat" span per Gemma attempt with
    model, duration, input/output/reasoning tokens, finish reason, outcome
    (ok / invalid_json / rejected / timeout / error) and rejection reasons
    (too_long, too_short, indoor, repeat, similar_to_disliked, taste_conflict).
    Local-context lookups (weather/places/SerpApi) show up as HTTP spans too.
  - Metrics: gemma.call.duration, gemma.tokens.input / .output, gemma.attempts,
    quest.generate.duration, gemma.rejections (by reason), gemma.timeouts.

Config (.env): SENTRY_DSN, SENTRY_ENVIRONMENT (default "development"),
SENTRY_TRACES_SAMPLE_RATE (default 1.0 - fine for a small app),
SENTRY_RELEASE (optional), SENTRY_SEND_PROMPTS=true to attach prompt/answer
text to the gen_ai spans (off by default - prompts contain the user's
preferences and location).
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("sidequest.observability")

try:  # optional dependency: the app works without it
    import sentry_sdk
except ImportError:  # pragma: no cover
    sentry_sdk = None  # type: ignore[assignment]

_enabled = False


def enabled() -> bool:
    return _enabled


def send_prompts() -> bool:
    return os.getenv("SENTRY_SEND_PROMPTS", "").strip().lower() in {"1", "true", "yes", "on"}


def init(**overrides: Any) -> bool:
    """Start Sentry if SENTRY_DSN is set (call once at startup). Returns whether it's on."""
    global _enabled
    dsn = overrides.pop("dsn", None) or os.getenv("SENTRY_DSN", "").strip()
    if not dsn or sentry_sdk is None:
        return False
    try:
        rate = float(os.getenv("SENTRY_TRACES_SAMPLE_RATE") or 1.0)
    except ValueError:
        rate = 1.0
    options: dict[str, Any] = dict(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT") or "development",
        release=os.getenv("SENTRY_RELEASE") or None,
        traces_sample_rate=rate,
        send_default_pii=False,  # no IPs, cookies or auth headers
        enable_logs=True,  # logging.warning/error lines become Sentry logs
        enable_metrics=True,
    )
    options.update(overrides)
    try:
        sentry_sdk.init(**options)
    except TypeError:  # older sentry-sdk without enable_logs / enable_metrics
        options.pop("enable_logs", None)
        options.pop("enable_metrics", None)
        sentry_sdk.init(**options)
    _enabled = True
    log.info("Sentry is on (environment=%s, traces=%s)", options["environment"], rate)
    return True


def set_user(user_id: str | None) -> None:
    """Tag events with the account id only (never email/name)."""
    if _enabled and user_id:
        sentry_sdk.set_user({"id": user_id})


class _NoSpan:
    def set_data(self, key: str, value: Any) -> None: ...
    def set_tag(self, key: str, value: Any) -> None: ...
    def set_status(self, status: str) -> None: ...


@contextmanager
def span(op: str, name: str, **data: Any) -> Iterator[Any]:
    """A Sentry span (child of the current request), or a do-nothing stand-in."""
    if not _enabled:
        yield _NoSpan()
        return
    with sentry_sdk.start_span(op=op, name=name) as s:
        for k, v in data.items():
            if v is not None:
                s.set_data(k, v)
        yield s


def metric(kind: str, name: str, value: float = 1, unit: str | None = None, **attributes: Any) -> None:
    """kind: count | distribution | gauge. Silently skipped if this sentry-sdk has no metrics."""
    if not _enabled:
        return
    try:
        fn = getattr(sentry_sdk.metrics, kind)
        attrs = {k: v for k, v in attributes.items() if v is not None}
        if kind == "count":
            fn(name, value, attributes=attrs)
        else:
            fn(name, value, unit=unit, attributes=attrs)
    except Exception:  # metrics are best-effort
        pass


def breadcrumb(message: str, **data: Any) -> None:
    if _enabled:
        sentry_sdk.add_breadcrumb(category="gemma", message=message, data=data, level="info")


def report_failed_generation(summary: dict[str, Any], error: BaseException) -> None:
    """One Sentry issue per quest that couldn't be generated, with every attempt attached."""
    if not _enabled:
        return
    with sentry_sdk.new_scope() as scope:
        scope.set_context("quest_generation", summary)
        scope.set_tag("gemma.model", summary.get("model"))
        scope.set_tag("gemma.outcome", summary.get("outcome"))
        scope.set_tag("gemma.attempts", summary.get("attempts"))
        reasons = summary.get("rejection_reasons") or []
        if reasons:
            scope.set_tag("gemma.last_rejection", reasons[-1])
        # Group by what went wrong, not by the (always different) message text.
        scope.fingerprint = ["quest-generation-failed", str(summary.get("outcome"))]
        sentry_sdk.capture_exception(error)
