"""Timezone-awareness of event-time parsing (USE_TZ=True migration).

Artifax returns Europe/London wall-clock times -> aware in TIME_ZONE.
O365/Graph returns UTC -> aware UTC.
"""
from datetime import timezone as stdlib_timezone
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone

from room_schedules import artifax_requests, o365_requests


class ArtifaxTimeParsingTests(SimpleTestCase):
    # custom_forms empty -> execute_chain returns None -> fallback to
    # start_time/end_time fields.
    def _event(self, start="19:30:00.000000Z", end="21:00:00.000000Z"):
        return {
            "custom_forms": [],
            "date": "2026-07-01",
            "start_time": start,
            "end_time": end,
        }

    def test_get_start_time_is_aware(self):
        out = artifax_requests.get_start_time(self._event())
        self.assertIsNotNone(out.tzinfo)
        self.assertIsNotNone(out.utcoffset())
        # Wall clock is preserved as the Europe/London local time given.
        local = timezone.localtime(out)
        self.assertEqual((local.hour, local.minute), (19, 30))

    def test_get_finish_time_is_aware(self):
        out = artifax_requests.get_finish_time(self._event())
        self.assertIsNotNone(out.tzinfo)
        local = timezone.localtime(out)
        self.assertEqual((local.hour, local.minute), (21, 0))

    def test_finish_time_before_break_point_rolls_to_next_day(self):
        # 02:00 <= HOUR_BREAK_POINT (04:00) -> pushed to the next day.
        out = artifax_requests.get_finish_time(
            self._event(end="02:00:00.000000Z")
        )
        self.assertIsNotNone(out.tzinfo)
        self.assertEqual(timezone.localtime(out).day, 2)


class _FakeResp:
    status = 200


class O365TimeParsingTests(SimpleTestCase):
    GRAPH_PAYLOAD = (
        '{"value": [{'
        '"id": "evt1", "subject": "Standup",'
        '"organizer": {"emailAddress": {"name": "Alice"}},'
        '"start": {"dateTime": "2026-07-01T09:00:00.000000"},'
        '"end": {"dateTime": "2026-07-01T09:30:00.000000"},'
        '"isCancelled": false}]}'
    )

    @mock.patch.object(o365_requests, "_get_access_token", return_value="tok")
    @mock.patch.object(o365_requests, "httplib2")
    def test_get_todays_events_returns_aware_utc(self, mock_httplib2, _tok):
        mock_httplib2.Http.return_value.request.return_value = (
            _FakeResp(), self.GRAPH_PAYLOAD.encode()
        )

        events = o365_requests.get_todays_events("room@example.com")

        self.assertEqual(len(events), 1)
        ev = events[0]
        for key in ("start_time", "end_time"):
            self.assertIsNotNone(ev[key].tzinfo, key)
            # Graph times are tagged UTC.
            self.assertEqual(ev[key].utcoffset(), stdlib_timezone.utc.utcoffset(None))
        self.assertEqual(ev["start_time"].hour, 9)
        self.assertEqual(ev["id"], "evt1")
