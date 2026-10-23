from decimal import Decimal

from django.conf import settings
from django.db import models


def D(valor):
    return Decimal(str(valor))


class Parametros(models.Model):
    """Valores que componen el precio (antes en la hoja "Estruc. Costos" y en cada COT).
    Hay una sola fila; se edita desde la pantalla Parámetros."""

    # Personal
    valor_dia_turismo = models.DecimalField('Valor del día en turismo', max_digits=14, decimal_places=2, default=D(480),
        help_text='Valor base del convenio. El sueldo diario por chofer es este valor × el factor de abajo.')
    factor_sueldo_conductor = models.DecimalField('Factor sueldo del conductor', max_digits=10, decimal_places=2, default=D(166),
        help_text='En la planilla: 166. Sueldo por día y chofer = valor del día × factor.')
    porcentaje_cargas_sociales = models.DecimalField('Cargas sociales (% del sueldo)', max_digits=6, decimal_places=2, default=D(50))
    no_remunerativo_mensual = models.DecimalField('No remunerativo mensual por chofer', max_digits=14, decimal_places=2, default=D(100000),
        help_text='Se reparte en 30 días y se cobra por cada día de viaje y chofer.')
    viatico_por_unidad = models.DecimalField('Viático (cada uno)', max_digits=14, decimal_places=2, default=D(30000))
    hotel_por_noche = models.DecimalField('Hotel por noche (por habitación)', max_digits=14, decimal_places=2, default=D(70000))

    # Vehículo
    precio_combustible = models.DecimalField('Precio del gasoil por litro', max_digits=14, decimal_places=2, default=D(2500))
    valor_adquisicion = models.DecimalField('Valor de compra del vehículo', max_digits=16, decimal_places=2, default=D(413055000),
        help_text='En la planilla: USD 301.500 × 1.370.')
    valor_residual = models.DecimalField('Valor residual del vehículo', max_digits=16, decimal_places=2, default=D(0))
    vida_util_meses = models.PositiveIntegerField('Vida útil del vehículo (meses)', default=60)
    seguro_mensual_flota = models.DecimalField('Seguro obligatorio mensual de la flota', max_digits=14, decimal_places=2, default=D(2000000))
    vehiculos_flota = models.PositiveIntegerField('Cantidad de vehículos de la flota', default=14,
        help_text='El seguro se reparte entre los vehículos y después por día de viaje.')

    # Gastos por viaje
    gastos_admin_mensuales = models.DecimalField('Gastos de administración mensuales', max_digits=16, decimal_places=2,
        default=D('14775723.20'),
        help_text='Sueldos de administración + cargas, internet, EDESA, alquileres (hoja "Hoja2" de la planilla).')
    divisor_prorrateo = models.PositiveIntegerField('Divisor para cargar gastos mensuales a cada viaje', default=300,
        help_text='Administración y depreciación mensual se dividen por este número en cada viaje (planilla: 30 × 10).')
    estacionamiento = models.DecimalField('Estacionamiento por viaje', max_digits=14, decimal_places=2, default=D(10000))
    lavadero = models.DecimalField('Lavadero por viaje', max_digits=14, decimal_places=2, default=D(340000))
    insumos_limpieza = models.DecimalField('Insumos de limpieza por viaje', max_digits=14, decimal_places=2, default=D(30000))

    # Márgenes y precio
    margen_minimo = models.DecimalField('Margen mínimo (%)', max_digits=6, decimal_places=2, default=D(20))
    margen_intermedio = models.DecimalField('Margen intermedio (%)', max_digits=6, decimal_places=2, default=D(50))
    margen_mercado = models.DecimalField('Margen valor de mercado (%)', max_digits=6, decimal_places=2, default=D(70))
    margen_optimo = models.DecimalField('Margen óptimo (%)', max_digits=6, decimal_places=2, default=D(100))
    precio_referencia_km = models.DecimalField('Precio de referencia por km', max_digits=14, decimal_places=2, default=D(3000),
        help_text='Para comparar: km totales × este precio.')
    porcentaje_iva = models.DecimalField('IVA (%)', max_digits=6, decimal_places=2, default=D('10.5'))

    # Word de la cotización
    porcentaje_sena = models.PositiveIntegerField('Seña (%)', default=40)
    vigencia_dias = models.PositiveIntegerField('Vigencia de la cotización (días)', default=7)
    incluye = models.TextField('Incluye (un renglón por ítem)', default=(
        'Traslado ida y regreso en vehículo mencionado.\n'
        'Viáticos de personal.\n'
        'Seguro de pasajero transportado.\n'
        'Ingresos, tickets, entradas, estacionamiento, tasas etc. de atracciones o destinos correspondientes al vehículo.'))
    no_incluye = models.TextField('No incluye (un renglón por ítem)', default='Gastos, movimientos y extras no especificados.')
    origen_habitual = models.CharField('Origen habitual de los viajes', max_length=120, default='Salta, Salta')

    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'parámetros de precio'
        verbose_name_plural = 'parámetros de precio'

    def __str__(self):
        return 'Parámetros de precio'

    @classmethod
    def actuales(cls):
        obj = cls.objects.first()
        return obj or cls.objects.create()


class TipoVehiculo(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    capacidad = models.PositiveIntegerField('Pasajeros')
    rendimiento_km_litro = models.DecimalField('Rendimiento (km por litro)', max_digits=6, decimal_places=2, default=D(3))
    descripcion_word = models.CharField('Cómo aparece en el Word', max_length=120,
        help_text='Ej.: "BUS  Piso Elevado 50 pasajeros"')
    orden = models.PositiveIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['orden', 'nombre']
        verbose_name = 'tipo de vehículo'
        verbose_name_plural = 'tipos de vehículo'

    def __str__(self):
        return f'{self.nombre} ({self.capacidad} pax)'


class Lugar(models.Model):
    """Lugares ya buscados en el mapa, para no volver a buscarlos."""
    busqueda = models.CharField(max_length=200, unique=True)
    nombre = models.CharField(max_length=300)
    lat = models.FloatField()
    lon = models.FloatField()
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['busqueda']
        verbose_name_plural = 'lugares'

    def __str__(self):
        return self.busqueda


class Cotizacion(models.Model):
    numero = models.PositiveIntegerField('N° de cotización', unique=True)
    fecha = models.DateField('Fecha')
    cliente = models.CharField(max_length=200)
    contacto = models.CharField('Teléfono / mail', max_length=200, blank=True)

    # Recorrido
    origen = models.CharField(max_length=120)
    paradas = models.TextField('Destinos / paradas', help_text='Uno por renglón, en orden.')
    ida_y_vuelta = models.BooleanField('Vuelve al origen', default=True)
    itinerario = models.CharField('Itinerario (como sale en el Word)', max_length=400)
    km_servicio = models.DecimalField('Km en servicio', max_digits=10, decimal_places=1, default=0)
    km_vacios = models.DecimalField('Km vacíos o margen', max_digits=10, decimal_places=1, default=0)
    km_mapa = models.DecimalField('Km según el mapa', max_digits=10, decimal_places=1, null=True, blank=True)

    salida = models.DateTimeField()
    regreso = models.DateTimeField()
    texto_salida = models.CharField('Aclaración de la salida', max_length=200, blank=True,
        help_text='Ej.: "desde Salta. Ida y regreso en el día."')
    dias = models.PositiveIntegerField('Días', default=1)
    noches = models.PositiveIntegerField('Noches', default=0)

    # Vehículo y personal
    vehiculo = models.ForeignKey(TipoVehiculo, on_delete=models.PROTECT)
    cantidad_vehiculos = models.PositiveIntegerField('Cantidad de vehículos', default=1)
    descripcion_vehiculo = models.CharField('Vehículo (como sale en el Word)', max_length=120)
    choferes = models.PositiveIntegerField('Choferes por vehículo', default=1)
    viaticos_por_chofer = models.PositiveIntegerField('Viáticos por chofer', default=1)
    habitaciones = models.PositiveIntegerField('Habitaciones de hotel', default=1)

    # Gastos que se eligen en cada viaje
    incluye_hotel = models.BooleanField('Hotel', default=True)
    incluye_estacionamiento = models.BooleanField('Estacionamiento', default=True)
    incluye_lavadero = models.BooleanField('Lavadero', default=True)
    peaje = models.DecimalField('Peajes ($)', max_digits=14, decimal_places=2, default=0)
    otros_gastos = models.DecimalField('Otros gastos ($)', max_digits=14, decimal_places=2, default=0)

    # Precio
    tarifa_neta = models.DecimalField('Tarifa final sin IVA', max_digits=16, decimal_places=2)
    costo_total = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    detalle = models.JSONField('Cálculo guardado', default=dict, blank=True)

    incluye = models.TextField('Incluye')
    no_incluye = models.TextField('No incluye')
    notas_internas = models.TextField('Notas internas (no salen en el Word)', blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    modificado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-numero']
        verbose_name = 'cotización'
        verbose_name_plural = 'cotizaciones'

    def __str__(self):
        return f'COT {self.numero} – {self.cliente}'

    @property
    def km_totales(self):
        return (self.km_servicio or 0) + (self.km_vacios or 0)

    @classmethod
    def proximo_numero(cls):
        ultimo = cls.objects.aggregate(m=models.Max('numero'))['m']
        return (ultimo or 302) + 1
