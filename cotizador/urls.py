from django.urls import path

from . import views

app_name = 'cotizador'

urlpatterns = [
    path('', views.lista, name='lista'),
    path('nueva/', views.nueva, name='nueva'),
    path('<int:pk>/', views.detalle, name='detalle'),
    path('<int:pk>/editar/', views.editar, name='editar'),
    path('<int:pk>/word/', views.descargar_word, name='word'),
    path('<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('<int:pk>/estado/', views.cambiar_estado, name='cambiar_estado'),
    path('<int:pk>/movimiento/', views.movimiento_nuevo, name='movimiento_nuevo'),
    path('movimiento/<int:pk>/eliminar/', views.movimiento_eliminar, name='movimiento_eliminar'),
    path('movimiento/<int:pk>/recibo/', views.descargar_recibo, name='recibo'),
    path('ventas/', views.ventas, name='ventas'),
    path('ventas/excel/', views.cuentas_excel, name='cuentas_excel'),
    path('estadisticas/', views.estadisticas, name='estadisticas'),
    path('clientes/', views.clientes, name='clientes'),
    path('clientes/nuevo/', views.cliente_form, name='cliente_nuevo'),
    path('clientes/<int:pk>/', views.cliente, name='cliente'),
    path('clientes/<int:pk>/editar/', views.cliente_form, name='cliente_editar'),
    path('clientes/<int:pk>/eliminar/', views.cliente_eliminar, name='cliente_eliminar'),
    path('calcular/', views.calcular, name='calcular'),
    path('buscar-km/', views.buscar_km, name='buscar_km'),
    path('parametros/', views.parametros, name='parametros'),
    path('vehiculos/', views.vehiculos, name='vehiculos'),
    path('vehiculos/<int:pk>/', views.vehiculos, name='vehiculo_editar'),
]
