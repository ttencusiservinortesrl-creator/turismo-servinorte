from django.contrib import admin

from .models import AsignacionUnidad, Cliente, Cotizacion, LineaVehiculo, Lugar, Movimiento, Parametros, TipoVehiculo


class LineaVehiculoInline(admin.TabularInline):
    model = LineaVehiculo
    extra = 0


class MovimientoInline(admin.TabularInline):
    model = Movimiento
    extra = 0


@admin.register(Cotizacion)
class CotizacionAdmin(admin.ModelAdmin):
    list_display = ['numero', 'fecha', 'cliente', 'estado', 'itinerario', 'tarifa_neta']
    list_filter = ['estado']
    search_fields = ['cliente__nombre', 'itinerario']
    inlines = [LineaVehiculoInline, MovimientoInline]


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'cuit', 'telefono', 'email', 'localidad']
    search_fields = ['nombre', 'cuit', 'telefono']


@admin.register(TipoVehiculo)
class TipoVehiculoAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'capacidad', 'rendimiento_km_litro', 'activo']


@admin.register(Lugar)
class LugarAdmin(admin.ModelAdmin):
    list_display = ['busqueda', 'nombre', 'lat', 'lon']
    search_fields = ['busqueda', 'nombre']


admin.site.register(Parametros)
admin.site.register(AsignacionUnidad)
