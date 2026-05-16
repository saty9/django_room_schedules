"""RoomInlineForm: a blank O365 calendar email is optional and stored as NULL."""
from django.test import TestCase

from room_schedules.admin import RoomInlineForm
from room_schedules.models import Venue, Room


class RoomInlineFormTests(TestCase):
    def test_blank_email_is_optional_and_becomes_none(self):
        form = RoomInlineForm(data={
            "name": "Room A",
            "artifax_id": 1,
            "allow_tablet_booking": False,
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["o365_calendar_email"])

    def test_provided_email_is_preserved(self):
        form = RoomInlineForm(data={
            "name": "Room B",
            "artifax_id": 2,
            "o365_calendar_email": "room-b@example.com",
            "allow_tablet_booking": False,
        })
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            form.cleaned_data["o365_calendar_email"], "room-b@example.com"
        )

    def test_multiple_rooms_without_email_do_not_collide(self):
        # NULLs are distinct under the unique constraint; empty strings would not be.
        venue = Venue.objects.create(name="V", artifax_id=10)
        for i in range(2):
            form = RoomInlineForm(data={
                "name": f"Room {i}",
                "artifax_id": 100 + i,
                "allow_tablet_booking": False,
            })
            self.assertTrue(form.is_valid(), form.errors)
            room = form.save(commit=False)
            room.venue = venue
            room.save()
        self.assertEqual(Room.objects.filter(o365_calendar_email__isnull=True).count(), 2)
