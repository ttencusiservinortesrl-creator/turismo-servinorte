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
    path('calcular/', views.calcular, name='calcular'),
    path('buscar-km/', views.buscar_km, name='buscar_km'),
    path('parametros/', views.parametros, name='parametros'),
    path('vehiculos/', views.vehiculos, name='vehiculos'),
    path('vehiculos/<int:pk>/', views.vehiculos, name='vehiculo_editar'),
]
