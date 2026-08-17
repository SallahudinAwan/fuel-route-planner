from django.contrib import admin
from django.urls import include, path

from planner.views import DemoView


urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("planner.urls")),
    path("", DemoView.as_view(), name="demo"),
]
