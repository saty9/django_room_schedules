"""cleanup_schedule prunes events older than 2 days using an aware `now`."""
import datetime

from django.test import TestCase
from django.utils import timezone

from room_schedules.models import Venue, Room, Event
from room_schedules.tasks import cleanup_schedule


class CleanupScheduleTests(TestCase):
    def setUp(self):
        venue = Venue.objects.create(name="V", artifax_id=1)
        self.room = Room.objects.create(
            name="R", venue=venue, artifax_id=1, o365_calendar_email=None
        )

    def _event(self, artifax_id, start):
        return Event.objects.create(
            name="E", room=self.room, organiser="",
            start_time=start, end_time=start + datetime.timedelta(hours=1),
            artifax_id=artifax_id,
        )

    def test_old_events_deleted_recent_kept(self):
        now = timezone.now()
        old = self._event(1, now - datetime.timedelta(days=3))
        recent = self._event(2, now - datetime.timedelta(hours=6))

        cleanup_schedule()

        self.assertFalse(Event.objects.filter(pk=old.pk).exists())
        self.assertTrue(Event.objects.filter(pk=recent.pk).exists())
