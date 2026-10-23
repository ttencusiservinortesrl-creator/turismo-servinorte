from django.contrib import admin

from .models import Cotizacion, Lugar, Parametros, TipoVehiculo


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ['numero', 'fecha', 'cliente', 'itinerario', 'tarifa_neta']
    search_fields = ['cliente', 'itinerario']


@admin.register(TipoVehiculo)
class TipoVehiculoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'capacidad', 'rendimiento_km_litro', 'activo']


@admin.register(Lugar)
class LugarAdmin(admin.ModelAdmin):
    list_display = ['busqueda', 'nombre', 'lat', 'lon']
    search_fields = ['busqueda', 'nombre']


admin.site.register(Parametros)
