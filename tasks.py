import datetime
from celery import shared_task
from django.utils import timezone
from room_schedules.models import Venue, Event

@shared_task(name='room_schedules.tasks.build_schedule')
def build_schedule():
    for venue in Venue.objects.all():
        venue.update_events()

@shared_task(name='room_schedules.tasks.cleanup_schedule')
def cleanup_schedule():
    Event.objects.filter(start_time__lt=timezone.now() - datetime.timedelta(days=2)).delete()
