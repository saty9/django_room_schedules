from django import forms
from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from room_schedules.models import Venue, Room


class RoomInlineForm(forms.ModelForm):
    class Meta:
        model = Room
        fields = ('name', 'artifax_id', 'o365_calendar_email', 'allow_tablet_booking')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A room without an O365 calendar is valid (Artifax-only rooms).
        self.fields['o365_calendar_email'].required = False

    def clean_o365_calendar_email(self):
        # Treat a blank email as NULL so it doesn't collide with the
        # unique constraint (empty strings would; NULLs don't).
        return self.cleaned_data.get('o365_calendar_email') or None


class RoomInline(TabularInline):
    model = Room
    form = RoomInlineForm
    extra = 0
    fields = ('name', 'artifax_id', 'o365_calendar_email', 'allow_tablet_booking')


@admin.register(Venue)
class VenueAdmin(ModelAdmin):
    list_display = ('id', 'name', 'artifax_id', 'overview_link')
    list_display_links = ('id', 'name')
    search_fields = ('name',)
    inlines = [RoomInline]

    def overview_link(self, obj):
        return format_html(
            '<a class="inline-block font-semibold h-6 leading-6 px-2 rounded-default text-[11px] uppercase whitespace-nowrap bg-green-100 text-green-700 dark:bg-green-500/20 dark:text-green-400" href="/event_schedules/{}">Overview</a>',
            obj.id,
        )
    overview_link.short_description = 'Screen Link'


@admin.register(Room)
class RoomAdmin(ModelAdmin):
    list_display = ('id', 'name', 'venue', 'artifax_id', 'o365_calendar_email', 'allow_tablet_booking', 'screen_link', 'tablet_link')
    list_display_links = ('id', 'name')
    search_fields = ('name', 'venue__name')
    list_filter = ('venue',)
    list_select_related = ('venue',)

    def screen_link(self, obj):
        return format_html(
            '<a class="inline-block font-semibold h-6 leading-6 px-2 rounded-default text-[11px] uppercase whitespace-nowrap bg-primary-100 text-primary-700 dark:bg-primary-500/20 dark:text-primary-400" href="/event_schedules/{}/{}">Screen</a>',
            obj.venue_id, obj.id,
        )
    screen_link.short_description = 'Screen Link'

    def tablet_link(self, obj):
        return format_html(
            '<a class="inline-block font-semibold h-6 leading-6 px-2 rounded-default text-[11px] uppercase whitespace-nowrap bg-blue-100 text-blue-700 dark:bg-blue-500/20 dark:text-blue-400" href="/event_schedules/{}/{}/tablet">Tablet</a>',
            obj.venue_id, obj.id,
        )
    tablet_link.short_description = 'Tablet Link'

