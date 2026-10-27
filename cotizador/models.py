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
    seguro_mensual_flota = models.DecimalField('Valor de la póliza de seguro (mensual, toda la flota)', max_digits=14,
        decimal_places=2, default=D(2000000),
        help_text='Seguro por viaje = póliza ÷ vehículos de la flota ÷ 30 × días del viaje.')
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

    # Impuestos sobre la venta (se calculan sobre el precio sin IVA)
    porcentaje_tissh = models.DecimalField('TISSH (%)', max_digits=6, decimal_places=2, default=D('0.6'),
        help_text='Tasa de Inspección de Seguridad, Salubridad e Higiene (municipal).')
    porcentaje_amt = models.DecimalField('AMT (%)', max_digits=6, decimal_places=2, default=D('2'))
    porcentaje_iibb = models.DecimalField('Ingresos Brutos (%)', max_digits=6, decimal_places=2, default=D('3.6'))

    # Viajes a futuro
    inflacion_mensual = models.DecimalField('Inflación mensual estimada (%)', max_digits=6, decimal_places=2,
        default=D('1.70'), help_text='Cuánto se espera que suban los costos por mes (gasoil, sueldos, hotel…).')
    proyectar_desde_dias = models.PositiveIntegerField('Proyectar si el viaje sale en más de (días)', default=30,
        help_text='Si el viaje es más adelante, los costos se llevan a la fecha de salida con la inflación.')

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

    # Diagrama de unidades (Excel en Drive)
    unidades_turismo = models.CharField('Unidades disponibles para turismo', max_length=200,
        default='61, 101, 81, 90, 91, 93, 94, 95, 96, 30',
        help_text='Números internos separados por coma, como figuran en el diagrama.')
    diagrama_drive_id = models.CharField('Código del diagrama en Drive', max_length=120, blank=True,
        default='15VVf08zLSZzklN-zUgKbRQxJIzlTqek_',
        help_text='Lo que va después de /d/ en el link del archivo. Cambia cada año (PL - DIAGRAMA DE VEHICULOS 2026, 2027…).')

    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        verbose_name = 'parámetros de precio'
        verbose_name_plural = 'parámetros de precio'

    def __str__(self):
        return 'Parámetros de precio'

    def lista_unidades(self):
        return [u.strip() for u in self.unidades_turismo.replace(';', ',').split(',') if u.strip()]

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


class Cliente(models.Model):
    nombre = models.CharField('Nombre o razón social', max_length=200)
    cuit = models.CharField('CUIT / DNI', max_length=20, blank=True)
    condicion_iva = models.CharField('Condición de IVA', max_length=40, blank=True, choices=[
        ('Consumidor Final', 'Consumidor Final'), ('Responsable Inscripto', 'Responsable Inscripto'),
        ('Monotributista', 'Monotributista'), ('Exento', 'Exento')])
    contacto = models.CharField('Persona de contacto', max_length=120, blank=True)
    telefono = models.CharField('Teléfono', max_length=60, blank=True)
    email = models.EmailField('Mail', blank=True)
    direccion = models.CharField('Dirección', max_length=200, blank=True)
    localidad = models.CharField(max_length=120, blank=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['nombre']

    def __str__(self):
        return self.nombre

    def saldo(self):
        """Lo que debe en total por sus viajes aceptados (positivo = nos debe)."""
        return sum((c.saldo() for c in self.cotizaciones.filter(estado=Cotizacion.ACEPTADA)), Decimal(0))


class Cotizacion(models.Model):
    PENDIENTE, ACEPTADA, RECHAZADA = 'pendiente', 'aceptada', 'rechazada'
    ESTADOS = [(PENDIENTE, 'Pendiente'), (ACEPTADA, 'Aceptada'), (RECHAZADA, 'Rechazada')]

    numero = models.PositiveIntegerField('N° de cotización', unique=True)
    fecha = models.DateField('Fecha')
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name='cotizaciones')
    estado = models.CharField(max_length=10, choices=ESTADOS, default=PENDIENTE)
    fecha_estado = models.DateField('Fecha de aceptación / rechazo', null=True, blank=True)
    motivo_rechazo = models.CharField('Motivo del rechazo', max_length=200, blank=True)

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
    # Los vehículos van en LineaVehiculo (puede haber varios tipos en una misma cotización).
    viaticos_por_chofer = models.PositiveIntegerField('Viáticos por chofer', default=1)
    habitaciones = models.PositiveIntegerField('Habitaciones de hotel por vehículo', default=1)

    # Gastos que se eligen en cada viaje
    incluye_hotel = models.BooleanField('Hotel', default=True)
    incluye_estacionamiento = models.BooleanField('Estacionamiento', default=True)
    incluye_lavadero = models.BooleanField('Lavadero', default=True)
    peaje = models.DecimalField('Peajes por vehículo ($)', max_digits=14, decimal_places=2, default=0)
    otros_gastos = models.DecimalField('Otros gastos ($)', max_digits=14, decimal_places=2, default=0)

    # Precio
    items_excluidos = models.TextField('Costos quitados de la suma', blank=True,
        help_text='Nombres de los ítems del costo que no se suman, separados por |.')
    proyectar_inflacion = models.BooleanField('Proyectar costos por inflación a la fecha del viaje', default=True)
    inflacion_mensual = models.DecimalField('Inflación mensual (%)', max_digits=6, decimal_places=2, default=D('1.70'))
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
    def vehiculos_texto(self):
        return ', '.join(f'{l.cantidad} × {l.vehiculo.nombre}' for l in self.lineas.all())

    @property
    def cantidad_vehiculos(self):
        return sum(l.cantidad for l in self.lineas.all())

    @property
    def km_totales(self):
        return (self.km_servicio or 0) + (self.km_vacios or 0)

    @classmethod
    def proximo_numero(cls):
        ultimo = cls.objects.aggregate(m=models.Max('numero'))['m']
        return (ultimo or 302) + 1

    @property
    def porcentaje_iva(self):
        return D(self.detalle.get('parametros', {}).get('IVA (%)', '10.5'))

    @property
    def total_con_iva(self):
        """Lo que se le cobra al cliente: tarifa + IVA (igual que el Word)."""
        return self.tarifa_neta + round(self.tarifa_neta * self.porcentaje_iva / 100)

    @property
    def importe_iva(self):
        return self.total_con_iva - self.tarifa_neta

    @property
    def porcentaje_sena(self):
        return int(self.detalle.get('parametros', {}).get('Seña (%)', 40))

    def total_cargos(self):
        return self.movimientos.filter(tipo=Movimiento.CARGO).aggregate(t=models.Sum('importe'))['t'] or D(0)

    def total_pagos(self):
        return self.movimientos.filter(tipo=Movimiento.PAGO).aggregate(t=models.Sum('importe'))['t'] or D(0)

    def saldo(self):
        return Decimal(self.total_cargos() - self.total_pagos()).quantize(Decimal('0.01'))

    def sena_requerida(self):
        return round(self.total_con_iva * self.porcentaje_sena / 100)

    def actualizar_cargo_automatico(self):
        """Al aceptar (o al cambiar el precio de una aceptada) el cargo del servicio sigue al total con IVA."""
        if self.estado != self.ACEPTADA:
            return
        cargo = self.movimientos.filter(automatico=True).first()
        concepto = f'Servicio COT {self.numero} (total con IVA)'
        if cargo:
            if cargo.importe != self.total_con_iva or cargo.concepto != concepto:
                cargo.importe = self.total_con_iva
                cargo.concepto = concepto
                cargo.save()
        else:
            Movimiento.objects.create(cotizacion=self, fecha=self.fecha_estado or self.fecha, tipo=Movimiento.CARGO,
                                      concepto=concepto, importe=self.total_con_iva, automatico=True)


class LineaVehiculo(models.Model):
    """Un tipo de vehículo dentro de una cotización (ej.: 1 bus piso elevado + 1 minibus)."""
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='lineas')
    vehiculo = models.ForeignKey(TipoVehiculo, on_delete=models.PROTECT, verbose_name='Vehículo')
    cantidad = models.PositiveIntegerField(default=1)
    choferes = models.PositiveIntegerField('Choferes c/u', default=1)
    descripcion = models.CharField('Cómo sale en el Word', max_length=120)
    orden = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['orden', 'id']
        verbose_name = 'vehículo de la cotización'
        verbose_name_plural = 'vehículos de la cotización'

    def __str__(self):
        return f'{self.cantidad} × {self.vehiculo.nombre}'


class AsignacionUnidad(models.Model):
    """Unidad (número interno del diagrama) asignada a un viaje vendido y anotada en el diagrama."""
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='asignaciones')
    unidad = models.CharField(max_length=20)
    desde = models.DateField()
    hasta = models.DateField()
    anotado_en = models.DateTimeField(auto_now_add=True)
    anotado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['desde', 'unidad']
        verbose_name = 'unidad asignada'
        verbose_name_plural = 'unidades asignadas'

    def __str__(self):
        return f'Unidad {self.unidad} – COT {self.cotizacion.numero}'


class Movimiento(models.Model):
    """Cuenta corriente de una venta: cargos (lo que debe) y pagos (lo que pagó)."""
    CARGO, PAGO = 'cargo', 'pago'
    MEDIOS = [('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('cheque', 'Cheque'),
              ('tarjeta', 'Tarjeta'), ('otro', 'Otro')]

    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.PROTECT, related_name='movimientos')
    fecha = models.DateField()
    tipo = models.CharField(max_length=10, choices=[(CARGO, 'Cargo (suma a la deuda)'), (PAGO, 'Pago / seña')])
    concepto = models.CharField(max_length=200)
    importe = models.DecimalField(max_digits=16, decimal_places=2)
    medio = models.CharField('Medio de pago', max_length=20, choices=MEDIOS, blank=True)
    referencia = models.CharField('Comprobante / referencia', max_length=120, blank=True,
        help_text='N° de recibo, factura, transferencia o cheque.')
    automatico = models.BooleanField(default=False, editable=False)
    numero_recibo = models.PositiveIntegerField('N° de recibo', null=True, blank=True, unique=True, editable=False)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['fecha', 'id']
        verbose_name = 'movimiento de cuenta corriente'
        verbose_name_plural = 'movimientos de cuenta corriente'

    def __str__(self):
        return f'{self.get_tipo_display()} {self.importe} – {self.concepto}'

    def save(self, *args, **kwargs):
        # Cada pago lleva su número de recibo correlativo.
        if self.tipo == self.PAGO and not self.numero_recibo:
            ultimo = Movimiento.objects.aggregate(m=models.Max('numero_recibo'))['m']
            self.numero_recibo = (ultimo or 0) + 1
        super().save(*args, **kwargs)
