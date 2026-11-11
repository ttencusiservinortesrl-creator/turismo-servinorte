from django.contrib import admin

from .models import (Articulo, Comprobante, EntregaInsumo, ImputacionComprobante, ImputacionPago, Liquidacion, Pago,
                     ServicioMAT)


class ServicioInline(admin.TabularInline):
    model = ServicioMAT
    extra = 0


@admin.register(Liquidacion)
class LiquidacionAdmin(admin.ModelAdmin):
    list_display = ['periodo', 'fecha_cierre', 'porcentaje_facturado', 'neto_manual']
    inlines = [ServicioInline]


class ImputacionPagoInline(admin.TabularInline):
    model = ImputacionPago
    extra = 0


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'medio', 'moneda', 'importe_origen', 'tipo_recibo', 'numero_recibo', 'anulado']
    list_filter = ['medio', 'tipo_recibo', 'anulado']
    inlines = [ImputacionPagoInline]


class ImputacionComprobanteInline(admin.TabularInline):
    model = ImputacionComprobante
    extra = 0


@admin.register(Comprobante)
class ComprobanteAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'tipo', 'numero', 'importe', 'motivo', 'anulado']
    list_filter = ['tipo', 'motivo', 'anulado']
    inlines = [ImputacionComprobanteInline]


admin.site.register(Articulo)
admin.site.register(EntregaInsumo)
