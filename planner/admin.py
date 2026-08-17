from django.contrib import admin

from .models import FuelStation, GeocodeCache, RoutePlanCache


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("opis_id", "name", "city", "state", "retail_price", "geocode_quality")
    list_filter = ("state", "geocode_quality")
    search_fields = ("name", "city", "address")


admin.site.register(GeocodeCache)
admin.site.register(RoutePlanCache)
