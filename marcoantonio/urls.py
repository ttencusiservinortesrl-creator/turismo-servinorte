from django.urls import path

from . import views

app_name = 'marcoantonio'

urlpatterns = [
    path('', views.tablero, name='tablero'),
    path('liquidaciones/nueva/', views.liquidacion_nueva, name='liquidacion_nueva'),
    path('liquidaciones/<int:pk>/', views.liquidacion, name='liquidacion'),
    path('liquidaciones/<int:pk>/editar/', views.liquidacion_editar, name='liquidacion_editar'),
    path('liquidaciones/<int:pk>/cerrar/', views.liquidacion_cerrar, name='liquidacion_cerrar'),
    path('liquidaciones/<int:pk>/servicios/', views.servicio_guardar, name='servicio_nuevo'),
    path('liquidaciones/<int:pk>/servicios/<int:servicio_pk>/', views.servicio_editar, name='servicio_editar'),
    path('liquidaciones/<int:pk>/servicios/<int:servicio_pk>/borrar/', views.servicio_borrar, name='servicio_borrar'),
    path('liquidaciones/<int:pk>/entregas/', views.entregas, name='entregas'),
    path('liquidaciones/<int:pk>/entregas/nueva/', views.entrega_guardar, name='entrega_nueva'),
    path('liquidaciones/<int:pk>/entregas/<int:entrega_pk>/borrar/', views.entrega_borrar, name='entrega_borrar'),
    path('salidas/', views.salidas, name='salidas'),
    path('salidas/nueva/', views.salida_nueva, name='salida_nueva'),
    path('salidas/<int:pk>/', views.salida, name='salida'),
    path('salidas/<int:pk>/insumos/', views.salida_insumo, name='salida_insumo'),
    path('salidas/<int:pk>/insumos/<int:entrega_pk>/borrar/', views.salida_insumo_borrar, name='salida_insumo_borrar'),
    path('liquidaciones/<int:pk>/entregas/<int:entrega_pk>/asignar/', views.entrega_asignar, name='entrega_asignar'),
    path('articulos/', views.articulos, name='articulos'),
    path('articulos/<int:pk>/', views.articulos, name='articulo_editar'),
    path('comprobantes/', views.comprobantes, name='comprobantes'),
    path('comprobantes/nuevo/', views.comprobante_form, name='comprobante_nuevo'),
    path('comprobantes/<int:pk>/', views.comprobante_form, name='comprobante_editar'),
    path('pagos/', views.pagos, name='pagos'),
    path('pagos/nuevo/', views.pago_form, name='pago_nuevo'),
    path('pagos/<int:pk>/', views.pago_form, name='pago_editar'),
    path('<str:tipo>/<int:pk>/anular/', views.anular, name='anular'),
    path('importar/', views.importar, name='importar'),
    path('excel/', views.descargar_excel, name='excel'),
]
