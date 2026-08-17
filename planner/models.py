from django.db import models


class FuelStation(models.Model):
    class GeocodeQuality(models.TextChoices):
        EXACT = "exact", "Exact address"
        CITY_CENTROID = "city_centroid", "City centroid"

    opis_id = models.BigIntegerField(primary_key=True)
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=250)
    city = models.CharField(max_length=120)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.CharField(max_length=30, blank=True)
    retail_price = models.DecimalField(max_digits=10, decimal_places=8)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=11, decimal_places=7)
    geocode_quality = models.CharField(
        max_length=20, choices=GeocodeQuality.choices
    )
    data_version = models.CharField(max_length=64, db_index=True)

    class Meta:
        ordering = ("opis_id",)
        indexes = [models.Index(fields=("latitude", "longitude"))]

    def __str__(self):
        return f"{self.name} ({self.city}, {self.state})"


class GeocodeCache(models.Model):
    normalized_query = models.CharField(max_length=300, primary_key=True)
    display_name = models.CharField(max_length=300)
    latitude = models.DecimalField(max_digits=10, decimal_places=7)
    longitude = models.DecimalField(max_digits=11, decimal_places=7)
    state = models.CharField(max_length=2)
    country_code = models.CharField(max_length=3)
    provider = models.CharField(max_length=30, default="openrouteservice")
    created_at = models.DateTimeField(auto_now_add=True)


class RoutePlanCache(models.Model):
    cache_key = models.CharField(max_length=64, primary_key=True)
    response = models.JSONField()
    data_version = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
