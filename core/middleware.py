import logging
import time
from time import monotonic

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.db import connection


logger = logging.getLogger("performance.sql")


class SlowQueryLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with connection.execute_wrapper(self._log_slow_query):
            return self.get_response(request)

    def _log_slow_query(self, execute, sql, params, many, context):
        started = monotonic()
        try:
            return execute(sql, params, many, context)
        finally:
            elapsed_ms = (monotonic() - started) * 1000
            if elapsed_ms >= settings.SLOW_QUERY_THRESHOLD_MS:
                logger.warning("Slow SQL %.1f ms: %s", elapsed_ms, sql)


class SessionExpiryMiddleware:
    SESSION_STARTED_AT_KEY = "_marcajix_session_started_at"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.session.get("_auth_user_id"):
            started_at = request.session.get(self.SESSION_STARTED_AT_KEY)
            now = int(time.time())
            if started_at is None:
                request.session[self.SESSION_STARTED_AT_KEY] = now
            elif now - int(started_at) >= settings.SESSION_MAX_AGE:
                request.session.flush()
                return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return self.get_response(request)