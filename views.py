import datetime
import hashlib

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST
from django.utils import timezone

# Create your views here.
from room_schedules.settings import HOUR_BREAK_POINT
from room_schedules.models import Venue, Event, Room


def room_led_status(request, venue_id, room_id):
    """Return 'AVAILABLE', 'WARNING', or 'BUSY' as plain text.
    - AVAILABLE: room is free and next event is >15 min away
    - WARNING: room is free but next event is within 15 min
    - BUSY: room is currently in use
    """
    room = get_object_or_404(Room, pk=room_id)
    now = timezone.now()
    
    # Check if room is currently in use
    current_event = Event.objects.filter(
        room=room,
        start_time__lte=now,
        end_time__gte=now,
        cancelled=False,
    ).first()
    
    if current_event:
        response = HttpResponse('BUSY', content_type='text/plain')
        response["Refresh"] = "60"  # refresh every 60 seconds
        return response
    
    # Room is available — check if next event is within 15 minutes
    next_event = Event.objects.filter(
        room=room,
        start_time__gt=now,
        cancelled=False,
    ).order_by('start_time').first()
    
    if next_event:
        time_until_next = (next_event.start_time - now).total_seconds() / 60
        if time_until_next <= 15:
            response = HttpResponse('WARNING', content_type='text/plain')
            response["Refresh"] = "60"  # refresh every 60 seconds
            return response
    
    response = HttpResponse('AVAILABLE', content_type='text/plain')
    response["Refresh"] = "60"  # refresh every 60 seconds
    return response


def show_venue(request, venue_id):
    venue = get_object_or_404(Venue, pk=venue_id)
    events = Event.objects.filter(room__venue=venue, end_time__gte=timezone.now(), cancelled=False)
    current_date = (timezone.localtime(timezone.now()) - datetime.timedelta(hours=HOUR_BREAK_POINT)).date()
    return render(request, "room_schedules/dashboard.html", {'events': events, 'current_date': current_date})


def _get_room_display_context(room):
    """Build the shared template context for room display views."""
    now = timezone.now()
    # localtime() so the Fringe-day .date() matches the Europe/London wall
    # clock the 04:00 break point is defined against.
    current_date = (timezone.localtime(now) - datetime.timedelta(hours=HOUR_BREAK_POINT)).date()

    # Get today's remaining events (not yet ended, not cancelled)
    events = list(
        Event.objects.filter(
            room=room,
            end_time__gte=now,
            cancelled=False,
        )
    )

    # Determine current and next event
    current_event = None
    next_event = None

    for event in events:
        if event.start_time <= now <= event.end_time:
            current_event = event
        elif event.start_time > now:
            if next_event is None:
                next_event = event

    # If there's no explicit next_event but we have a current event,
    # find the first event after the current one ends
    if current_event and next_event is None:
        for event in events:
            if event.start_time > current_event.end_time:
                next_event = event
                break

    is_available = current_event is None

    # Determine if we're in warning state (available but next event within 15 minutes)
    is_warning = False
    if is_available and next_event:
        time_until_next = (next_event.start_time - now).total_seconds() / 60
        is_warning = time_until_next <= 15

    # Compute the start of the current free period (for progress bar).
    # This is the end time of the most recent event that finished before now.
    free_since = None
    if is_available:
        previous_event = (
            Event.objects.filter(
                room=room,
                end_time__lte=now,
                cancelled=False,
            )
            .order_by('-end_time')
            .first()
        )
        if previous_event:
            free_since = previous_event.end_time
        else:
            # No earlier event today — free since the start of the display day
            free_since = timezone.make_aware(datetime.datetime.combine(
                current_date,
                datetime.time(HOUR_BREAK_POINT, 0),
            ))

    # Timestamps for JS countdowns. localtime() so the ISO carries an offset
    # (e.g. +01:00) — browsers' new Date(iso) then parse the correct instant.
    current_event_end_iso = timezone.localtime(current_event.end_time).isoformat() if current_event else None
    current_event_start_iso = timezone.localtime(current_event.start_time).isoformat() if current_event else None
    next_event_start_iso = timezone.localtime(next_event.start_time).isoformat() if next_event else None
    free_since_iso = timezone.localtime(free_since).isoformat() if free_since else None

    return {
        'room': room,
        'events': events,
        'current_date': current_date,
        'current_event': current_event,
        'next_event': next_event,
        'is_available': is_available,
        'is_warning': is_warning,
        'now_iso': timezone.localtime(now).isoformat(),
        'current_event_end_iso': current_event_end_iso,
        'current_event_start_iso': current_event_start_iso,
        'next_event_start_iso': next_event_start_iso,
        'free_since_iso': free_since_iso,
    }


def show_room(request, venue_id, room_id):
    room = get_object_or_404(Room, pk=room_id)
    context = _get_room_display_context(room)
    return render(request, "room_schedules/room_screen.html", context)


def show_room_tablet(request, venue_id, room_id):
    room = get_object_or_404(Room, pk=room_id)
    context = _get_room_display_context(room)
    return render(request, "room_schedules/room_tablet.html", context)


@csrf_exempt
@require_POST
def book_adhoc(request, venue_id, room_id):
    """Create an adhoc booking for a currently-free O365 room.

    POST params:
      duration_minutes: int, multiple of 5, 5–240  (0 means "until next booking")
    """
    from room_schedules.o365_requests import create_adhoc_booking

    room = get_object_or_404(Room, pk=room_id)

    if not room.allow_tablet_booking or not room.o365_calendar_email:
        return JsonResponse({'error': 'Room does not support adhoc booking.'}, status=400)

    now = timezone.now()

    current_event = Event.objects.filter(
        room=room, start_time__lte=now, end_time__gte=now, cancelled=False
    ).first()
    if current_event:
        return JsonResponse({'error': 'Room is currently in use.'}, status=409)

    try:
        duration_minutes = int(request.POST.get('duration_minutes', 0))
    except (ValueError, TypeError):
        return JsonResponse({'error': 'Invalid duration.'}, status=400)

    MAX_MINUTES = 240
    next_event = Event.objects.filter(
        room=room, start_time__gt=now, cancelled=False
    ).order_by('start_time').first()

    if duration_minutes == 0:
        # "Until next booking" — cap at 4 hours
        if next_event:
            end_dt = min(next_event.start_time, now + datetime.timedelta(minutes=MAX_MINUTES))
        else:
            end_dt = now + datetime.timedelta(minutes=MAX_MINUTES)
    else:
        if duration_minutes < 5 or duration_minutes > MAX_MINUTES or duration_minutes % 5 != 0:
            return JsonResponse({'error': 'Duration must be a multiple of 5 between 5 and 240.'}, status=400)
        end_dt = now + datetime.timedelta(minutes=duration_minutes)
        if next_event and next_event.start_time < end_dt:
            end_dt = next_event.start_time

    start_dt = now.replace(second=0, microsecond=0)

    try:
        o365_id = create_adhoc_booking(room.o365_calendar_email, start_dt, end_dt)
    except RuntimeError as e:
        return JsonResponse({'error': str(e)}, status=502)

    Event.objects.create(
        name="Adhoc Booking",
        room=room,
        organiser="",
        start_time=start_dt,
        end_time=end_dt,
        o365_event_id=o365_id,
    )

    return JsonResponse({'ok': True})


def room_state_hash(request, venue_id, room_id):
    """Return a short hash of the room's current event state.

    Clients poll this endpoint and only reload when the hash changes,
    avoiding unnecessary full-page refreshes.
    """
    room = get_object_or_404(Room, pk=room_id)
    now = timezone.now()

    events = Event.objects.filter(
        room=room,
        end_time__gte=now,
        cancelled=False,
    ).order_by('start_time').values_list('pk', 'name', 'start_time', 'end_time', 'cancelled')

    # Build a deterministic fingerprint from the event data
    raw = '|'.join(
        f'{pk},{name},{timezone.localtime(st).isoformat()},{timezone.localtime(et).isoformat()},{c}'
        for pk, name, st, et, c in events
    )
    digest = hashlib.md5(raw.encode()).hexdigest()[:12]

    response = JsonResponse({'hash': digest})
    response['Cache-Control'] = 'no-store'
    return response
