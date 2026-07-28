"""
observability.py — Optional error tracking (Sentry).

A complete no-op unless SENTRY_DSN is set AND sentry-sdk is installed, so dev
and self-hosted deploys run untouched and with no extra dependency.

Arogo holds health data, so PII is scrubbed hard: request bodies, query
strings, headers, cookies and user identity are dropped before an event
leaves the process — only the exception, its stack, and a coarse `component`
tag are sent. Init is idempotent per process.
"""
import os

_active = False


def init_error_tracking(component: str = "web") -> bool:
    """Turn on Sentry if configured. Returns True if active, else False (no-op).

    `component` distinguishes the web process from the scheduler worker in the
    Sentry dashboard, since they run separately in production.
    """
    global _active
    if _active:
        return True
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        print("[obs] SENTRY_DSN is set but sentry-sdk isn't installed — "
              "error tracking disabled. `pip install sentry-sdk` to enable.")
        return False

    def _scrub(event, hint):
        # Drop everything that could carry health data or identify a person.
        event.pop("request", None)      # url, query string, body, headers, cookies
        event.pop("user", None)         # id / email / ip
        return event

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENV", "production"),
        # Render exposes the deployed commit; helps pin a regression to a deploy.
        release=os.environ.get("RENDER_GIT_COMMIT") or None,
        send_default_pii=False,
        traces_sample_rate=0.0,         # errors only — no performance/PII spans
        max_breadcrumbs=20,
        before_send=_scrub,
    )
    sentry_sdk.set_tag("component", component)
    _active = True
    print(f"[obs] Sentry error tracking active ({component})")
    return True


def capture(exc: BaseException, **tags) -> None:
    """Report a caught exception if tracking is active; a no-op otherwise.

    Used for background-job failures that are swallowed with a `try/except`
    (scheduler jobs) so they don't vanish into stderr on a headless worker.
    """
    if not _active:
        return
    try:
        import sentry_sdk
        if tags:
            with sentry_sdk.push_scope() as scope:
                for k, v in tags.items():
                    scope.set_tag(k, v)
                sentry_sdk.capture_exception(exc)
        else:
            sentry_sdk.capture_exception(exc)
    except Exception:
        pass        # observability must never break the thing it observes
