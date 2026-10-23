from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('ingresar/', auth_views.LoginView.as_view(), name='login'),
    path('salir/', auth_views.LogoutView.as_view(), name='logout'),
    path('cotizaciones/', include('cotizador.urls')),
    path('', RedirectView.as_view(pattern_name='cotizador:lista', permanent=False)),
]
