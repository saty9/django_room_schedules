import json
import httplib2
import msal
from datetime import datetime, timedelta, timezone as stdlib_timezone

from django.conf import settings
from django.utils import timezone

from room_schedules.settings import (
    HOUR_BREAK_POINT,
    O365_CLIENT_ID, O365_CLIENT_SECRET, O365_TENANT_ID,
    O365_DELEGATED_USERNAME, O365_DELEGATED_PASSWORD,
)

GRAPH_API = "https://graph.microsoft.com/v1.0"

# Module-level singleton so MSAL's in-memory token cache is reused across rooms
# within a single Celery worker process, avoiding a token request per room.
_msal_app = None


def _get_msal_app():
    global _msal_app
    if _msal_app is None:
        _msal_app = msal.ConfidentialClientApplication(
            client_id=O365_CLIENT_ID,
            client_credential=O365_CLIENT_SECRET,
            authority=f"https://login.microsoftonline.com/{O365_TENANT_ID}",
        )
    return _msal_app


def _get_access_token():
    app = _get_msal_app()
    if O365_DELEGATED_USERNAME and O365_DELEGATED_PASSWORD:
        result = app.acquire_token_by_username_password(
            username=O365_DELEGATED_USERNAME,
            password=O365_DELEGATED_PASSWORD,
            scopes=["https://graph.microsoft.com/Calendars.ReadWrite"],
        )
    else:
        result = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"]
        )
    if "access_token" not in result:
        raise RuntimeError(
            f"O365 authentication failed: {result.get('error_description', result)}"
        )
    return result["access_token"]


def get_todays_events(room_email):
    """
    Fetch today's events for an O365 room resource mailbox via the Microsoft Graph API.

    Uses the same fringe-day boundary as the Artifax integration:
    the day runs from HOUR_BREAK_POINT (04:00) to 03:59 the next morning.

    Returns a list of dicts:
        {id, name, organiser, start_time, end_time, cancelled}
    where start_time and end_time are timezone-aware UTC datetimes (Graph's
    default), suitable for storing with USE_TZ=True.
    """
    # Aware Europe/London now: .hour is the local wall clock the Fringe-day
    # 04:00 break is defined against; the window bounds carry an offset so
    # Graph interprets startDateTime/endDateTime correctly.
    now = timezone.localtime(timezone.now())
    if now.hour < HOUR_BREAK_POINT:
        start = (now - timedelta(days=1)).replace(
            hour=HOUR_BREAK_POINT, minute=0, second=0, microsecond=0
        )
    else:
        start = now.replace(hour=HOUR_BREAK_POINT, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=24) - timedelta(seconds=1)

    token = _get_access_token()
    h = httplib2.Http()
    url = (
        f"{GRAPH_API}/users/{room_email}/calendarView"
        f"?startDateTime={start.isoformat()}&endDateTime={end.isoformat()}"
        f"&$select=id,subject,organizer,start,end,isCancelled"
        f"&$top=100"
    )
    response, content = h.request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )

    if response.status != 200:
        raise RuntimeError(
            f"Graph API error {response.status} for {room_email}: {content}"
        )

    results = []
    for item in json.loads(content).get("value", []):
        results.append({
            "id": item["id"],
            "name": item.get("subject", ""),
            "organiser": item.get("organizer", {}).get("emailAddress", {}).get("name", ""),
            # Graph returns these in UTC; tag them aware-UTC for USE_TZ=True.
            "start_time": datetime.fromisoformat(item["start"]["dateTime"].rstrip("Z")).replace(tzinfo=stdlib_timezone.utc),
            "end_time": datetime.fromisoformat(item["end"]["dateTime"].rstrip("Z")).replace(tzinfo=stdlib_timezone.utc),
            "cancelled": item.get("isCancelled", False),
        })
    return results


def create_adhoc_booking(room_email, start_dt, end_dt):
    """Create an 'Adhoc Booking' event on the room's O365 calendar.

    start_dt and end_dt are timezone-aware datetimes; they are sent as
    Europe/London wall-clock paired with the timeZone field.
    Returns the new event's O365 id string.
    """
    token = _get_access_token()
    h = httplib2.Http()
    url = f"{GRAPH_API}/users/{room_email}/calendar/events"
    # Naive local (Europe/London) wall clock to match the timeZone field.
    local_start = timezone.localtime(start_dt).replace(tzinfo=None)
    local_end = timezone.localtime(end_dt).replace(tzinfo=None)
    body = json.dumps({
        "subject": "Adhoc Booking",
        "start": {"dateTime": local_start.isoformat(), "timeZone": settings.TIME_ZONE},
        "end":   {"dateTime": local_end.isoformat(),   "timeZone": settings.TIME_ZONE},
    })
    response, content = h.request(
        url,
        method="POST",
        body=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    if response.status not in (200, 201):
        raise RuntimeError(
            f"Graph API error {response.status} creating adhoc booking for {room_email}: {content}"
        )
    return json.loads(content)["id"]
