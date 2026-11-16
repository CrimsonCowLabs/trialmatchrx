"""`POST /api/access-requests`: the request-access form on `/` (SPEC.md "Marketing and
accounts"). Public, no session (SPEC.md Enforcement lists it among the exemptions). It's a
POST, so the CSRF guard still wants `X-Requested-With`, which the web client always sends.

Not an agent run, so like sign-in its decisions go to a logger rather than a TraceRecorder
(see `app/routers/auth.py`).
"""

import logging

from fastapi import APIRouter, HTTPException, Request

from app import access_requests
from app.auth.client_ip import request_ip
from app.schemas import ACCESS_REQUESTS_THROTTLED, AccessRequestCreate

log = logging.getLogger("app.access_requests")

router = APIRouter(prefix="/api/access-requests", tags=["access-requests"])


@router.post(
    "",
    status_code=204,
    responses={
        422: {"description": "A field is missing, too long, or not valid"},
        429: {"description": ACCESS_REQUESTS_THROTTLED},
    },
)
def create_access_request(body: AccessRequestCreate, request: Request) -> None:
    """Send a request for access. A filled honeypot gets the same 204 and stores nothing; a
    4th stored request within an hour from one IP is a 429."""
    ip = request_ip(request)
    outcome = access_requests.submit(body, ip)
    log.info("access request %s ip=%s", outcome, ip)
    if outcome == "throttled":
        raise HTTPException(status_code=429, detail=ACCESS_REQUESTS_THROTTLED)
