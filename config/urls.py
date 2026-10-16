from django.contrib import admin
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import include, path

from turni import views as turni_views


def health(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('', lambda request: redirect('turni:home')),
    path('admin/', admin.site.urls),
    path('health/', health),
    path('turni/', include('turni.urls')),
    path('manifest.webmanifest', turni_views.manifest, name='manifest'),
    path('sw.js', turni_views.service_worker, name='service_worker'),
]
