"""Control de Marco Antonio Tours (empresa relacionada): servicios e insumos que le presta Servinorte,
liquidación mensual en dos partes (facturada con IVA y en efectivo sin factura), comprobantes y pagos.

Reemplaza la planilla "PL - MARCO ANTONIO TOURS NACIONAL 2026".
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum

CERO = Decimal('0')
MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
         'noviembre', 'diciembre']

FACTURADA, EFECTIVO = 'facturada', 'efectivo'
PARTES = [(FACTURADA, 'Parte facturada (neto + IVA)'), (EFECTIVO, 'Parte en efectivo sin factura')]


def estado_de(importe, pagado):
    # Menos de $1 de diferencia se toma como pagado (redondeo de centavos al repartir).
    if importe <= Decimal('0.01'):
        return 'sin_importe'
    if importe - pagado < 1:
        return 'pagada'
    return 'parcial' if pagado >= 1 else 'pendiente'


ESTADOS_PAGO = {'pagada': 'Pagada', 'parcial': 'Pago parcial', 'pendiente': 'Pendiente', 'sin_importe': 'Sin precio'}


def redondear(valor):
    return Decimal(valor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _suma(qs, campo='importe'):
    # Sum() en SQLite devuelve decimales de más: se redondea a centavos.
    return redondear(qs.aggregate(t=Sum(campo))['t'] or CERO)


def pesos_texto(valor):
    """1234567.5 -> '1.234.567,50'"""
    return f'{valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')


class Liquidacion(models.Model):
    periodo = models.DateField('Mes', unique=True, help_text='Se guarda el primer día del mes.')
    fecha_cierre = models.DateField('Fecha de cierre', null=True, blank=True)
    porcentaje_facturado = models.DecimalField('% que se factura', max_digits=5, decimal_places=2, default=Decimal(50),
        help_text='El resto es la parte en efectivo sin factura.')
    porcentaje_iva = models.DecimalField('IVA de la parte facturada (%)', max_digits=5, decimal_places=2, default=Decimal('10.5'))
    precio_agua = models.DecimalField('Precio unitario del agua', max_digits=12, decimal_places=2, default=Decimal(455))
    neto_manual = models.DecimalField('Total neto cargado a mano', max_digits=16, decimal_places=2, null=True, blank=True,
        help_text='Solo para meses sin detalle (importados de la planilla). Si está vacío, se suman servicios, agua e insumos.')
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['periodo']
        verbose_name = 'liquidación'
        verbose_name_plural = 'liquidaciones'

    def __str__(self):
        return f'Liquidación {self.nombre}'

    @property
    def cerrada(self):
        return self.fecha_cierre is not None

    @property
    def nombre(self):
        return f'{MESES[self.periodo.month - 1].capitalize()} {self.periodo.year}'

    @property
    def codigo(self):
        return f'LIQ-{self.periodo.year}-{self.periodo.month:02d}'

    # --- Composición ---
    def total_servicios(self):
        return sum((s.tarifa for s in self.servicios.all()), CERO)

    def total_agua(self):
        return redondear(sum((s.unidades_agua for s in self.servicios.all()), 0) * self.precio_agua)

    def total_insumos(self, categoria=None):
        entregas = self.entregas.select_related('articulo')
        if categoria:
            entregas = entregas.filter(articulo__categoria=categoria)
        return redondear(sum((e.total for e in entregas), CERO))

    def neto(self):
        if self.neto_manual is not None:
            return self.neto_manual
        return redondear(self.total_servicios() + self.total_agua() + self.total_insumos())

    def facturada_neto(self):
        return redondear(self.neto() * self.porcentaje_facturado / 100)

    def facturada_iva(self):
        return redondear(self.facturada_neto() * self.porcentaje_iva / 100)

    def importe(self, parte):
        """Lo que se liquida de cada parte: facturada = neto + IVA; efectivo = neto sin IVA."""
        if parte == FACTURADA:
            return self.facturada_neto() + self.facturada_iva()
        return redondear(self.neto() - self.facturada_neto())

    def total(self):
        return self.importe(FACTURADA) + self.importe(EFECTIVO)

    # --- Pagos y comprobantes imputados ---
    def pagado(self, parte):
        return _suma(self.imputaciones_pagos.filter(parte=parte, pago__anulado=False))

    def comprobado(self, parte):
        return _suma(self.imputaciones_comprobantes.filter(parte=parte, comprobante__anulado=False))

    def saldo(self, parte):
        return self.importe(parte) - self.pagado(parte)

    def sin_comprobante(self, parte):
        return self.importe(parte) - self.comprobado(parte)

    def importe_de_salidas(self, parte):
        return sum((sal.importe(parte) for sal in self.servicios.all()), CERO)

    def resto_del_mes(self, parte):
        """Lo que no es de ninguna salida: insumos del mes sin salida y, si el neto se cargó a mano, la diferencia."""
        return self.importe(parte) - self.importe_de_salidas(parte)

    def reparto_pagos(self):
        """Cuánto está pagado de cada salida, por parte: {salida_id: {parte: pagado}, None: {parte: resto}}.

        Lo aplicado a una salida cuenta para esa salida. Lo aplicado al mes en general se reparte entre las salidas
        del mes de la más vieja a la más nueva; si sobra, queda para el resto del mes (insumos sin salida, ajuste)."""
        salidas = list(self.servicios.all())
        reparto = {sal.pk: {} for sal in salidas}
        reparto[None] = {}
        for parte, _ in PARTES:
            imputaciones = [i for i in self.imputaciones_pagos.all() if i.parte == parte and not i.pago.anulado]
            del_mes = sum((i.importe for i in imputaciones if i.servicio_id is None), CERO)
            for sal in salidas:
                directo = sum((i.importe for i in imputaciones if i.servicio_id == sal.pk), CERO)
                falta = max(sal.importe(parte) - directo, CERO)
                tomado = min(del_mes, falta)
                del_mes -= tomado
                reparto[sal.pk][parte] = {'directo': directo, 'repartido': tomado, 'pagado': directo + tomado}
            reparto[None][parte] = del_mes
        return reparto

    def aplicaciones_pagos(self):
        """Qué pagos cubren cada salida, con el mismo criterio que reparto_pagos:
        {salida_id: [{'pago', 'parte', 'importe'}]}. Los pagos del mes se toman del más viejo al más nuevo."""
        salidas = list(self.servicios.all())
        res = {sal.pk: [] for sal in salidas}
        for parte, _ in PARTES:
            imputaciones = [i for i in self.imputaciones_pagos.all() if i.parte == parte and not i.pago.anulado]
            for i in imputaciones:
                if i.servicio_id in res:
                    res[i.servicio_id].append({'pago': i.pago, 'parte': parte, 'importe': i.importe})
            cola = [[i, i.importe] for i in sorted((i for i in imputaciones if i.servicio_id is None),
                                                   key=lambda i: (i.pago.fecha, i.pago_id, i.pk))]
            for sal in salidas:
                directo = sum((i.importe for i in imputaciones if i.servicio_id == sal.pk), CERO)
                falta = max(sal.importe(parte) - directo, CERO)
                while falta > 0 and cola:
                    tomado = min(cola[0][1], falta)
                    if tomado > 0:
                        res[sal.pk].append({'pago': cola[0][0].pago, 'parte': parte, 'importe': tomado})
                    falta -= tomado
                    cola[0][1] -= tomado
                    if cola[0][1] <= 0:
                        cola.pop(0)
        for lista in res.values():
            lista.sort(key=lambda a: (a['pago'].fecha, a['pago'].pk))
        return res

    def resumen(self):
        partes = {}
        for parte, nombre in PARTES:
            partes[parte] = {'nombre': nombre, 'importe': self.importe(parte), 'pagado': self.pagado(parte),
                             'saldo': self.saldo(parte), 'comprobado': self.comprobado(parte),
                             'sin_comprobante': self.sin_comprobante(parte)}
        return partes


class ServicioMAT(models.Model):
    TARIFAS = [('minima', 'Mínima'), ('intermedia', 'Intermedia'), ('optima', 'Óptima'), ('otra', 'Otra (a mano)')]

    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.CASCADE, related_name='servicios')
    fecha = models.DateField()
    unidad = models.CharField('Unidad / vehículo', max_length=60)
    servicio = models.CharField(max_length=200)
    tarifa_minima = models.DecimalField('Tarifa mínima', max_digits=14, decimal_places=2, default=0)
    tarifa_intermedia = models.DecimalField('Tarifa intermedia', max_digits=14, decimal_places=2, default=0)
    tarifa_optima = models.DecimalField('Tarifa óptima', max_digits=14, decimal_places=2, default=0)
    tarifa_elegida = models.CharField('Tarifa vendida', max_length=12, choices=TARIFAS, blank=True)
    tarifa_otra = models.DecimalField('Tarifa a mano', max_digits=14, decimal_places=2, null=True, blank=True)
    unidades_agua = models.PositiveIntegerField('Unidades de agua', default=0)
    observaciones = models.CharField(max_length=200, blank=True)
    cotizacion = models.OneToOneField('cotizador.Cotizacion', verbose_name='Viene de la cotización', null=True, blank=True,
                                      on_delete=models.SET_NULL, related_name='salida_mat')

    class Meta:
        ordering = ['fecha', 'id']
        verbose_name = 'salida'

    def __str__(self):
        return f'{self.fecha:%d/%m} {self.servicio}'

    @property
    def tarifa(self):
        """La tarifa vendida (0 si todavía no se eligió)."""
        return {'minima': self.tarifa_minima, 'intermedia': self.tarifa_intermedia, 'optima': self.tarifa_optima,
                'otra': self.tarifa_otra or CERO}.get(self.tarifa_elegida, CERO)

    @property
    def costo_agua(self):
        return redondear(self.unidades_agua * self.liquidacion.precio_agua)

    def total_insumos(self):
        return redondear(sum((e.total for e in self.insumos.all()), CERO))

    def neto(self):
        """Precio + agua + insumos que llevó la salida."""
        return redondear(self.tarifa + self.costo_agua + self.total_insumos())

    def importe(self, parte):
        liq = self.liquidacion
        facturada_neto = redondear(self.neto() * liq.porcentaje_facturado / 100)
        if parte == FACTURADA:
            return facturada_neto + redondear(facturada_neto * liq.porcentaje_iva / 100)
        return redondear(self.neto() - facturada_neto)

    def total(self):
        return self.importe(FACTURADA) + self.importe(EFECTIVO)

    def estado_pagos(self, reparto=None):
        """Por parte: importe, pagado (directo + repartido del mes), saldo y estado. Más el estado general."""
        reparto = (reparto or self.liquidacion.reparto_pagos())[self.pk]
        partes = {}
        for parte, nombre in PARTES:
            importe = self.importe(parte)
            pagado = reparto[parte]['pagado']
            saldo = importe - pagado
            partes[parte] = {'nombre': nombre, 'importe': importe, 'pagado': pagado, 'saldo': saldo,
                             'directo': reparto[parte]['directo'], 'repartido': reparto[parte]['repartido'],
                             'estado': estado_de(importe, pagado)}
        total, pagado = self.total(), partes[FACTURADA]['pagado'] + partes[EFECTIVO]['pagado']
        return {'partes': partes, 'total': total, 'pagado': pagado, 'saldo': total - pagado,
                'estado': estado_de(total, pagado)}


class Articulo(models.Model):
    CATEGORIAS = [('colacion', 'Colaciones'), ('limpieza', 'Artículos de limpieza'), ('otro', 'Otros')]

    codigo = models.PositiveIntegerField('Código', unique=True)
    nombre = models.CharField('Artículo', max_length=120)
    categoria = models.CharField('Sección', max_length=10, choices=CATEGORIAS, default='colacion')
    precio = models.DecimalField('Precio unitario', max_digits=14, decimal_places=2, default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['categoria', 'codigo']
        verbose_name = 'artículo'

    def __str__(self):
        return f'{self.codigo} – {self.nombre}'


class EntregaInsumo(models.Model):
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.CASCADE, related_name='entregas')
    servicio = models.ForeignKey(ServicioMAT, null=True, blank=True, on_delete=models.SET_NULL, related_name='insumos',
                                 verbose_name='Salida', help_text='Vacío = insumos del mes, sin una salida en particular.')
    fecha = models.DateField()
    articulo = models.ForeignKey(Articulo, on_delete=models.PROTECT, related_name='entregas', verbose_name='Artículo')
    cantidad = models.DecimalField(max_digits=10, decimal_places=2)
    precio_unitario = models.DecimalField('Precio unitario', max_digits=14, decimal_places=4,
        help_text='Se copia del artículo al cargar; si cambia el precio, las entregas ya cargadas no cambian.')
    observaciones = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ['fecha', 'articulo__codigo']
        verbose_name = 'entrega de insumos'
        verbose_name_plural = 'entregas de insumos'

    @property
    def total(self):
        return redondear(self.cantidad * self.precio_unitario)


COMPROBANTES_EN_NEGRO = ('FAC M', 'NC M')


def forzar_efectivo(objeto):
    """Pasa a la parte en efectivo las imputaciones de un comprobante M o de un pago en negro.
    Devuelve cuántas cambió."""
    if not objeto.en_negro:
        return 0
    return objeto.imputaciones.exclude(parte=EFECTIVO).update(parte=EFECTIVO)


class Comprobante(models.Model):
    TIPOS = [('FAC A', 'Factura A'), ('FAC M', 'Factura M'), ('FAC B', 'Factura B'), ('NC A', 'Nota de crédito A'),
             ('NC M', 'Nota de crédito M'), ('ND A', 'Nota de débito A'), ('OTRO', 'Otro')]
    MOTIVOS = [('servicio', 'Servicios del mes'), ('a_cuenta', 'A cuenta (al recibir un pago)'), ('cierre', 'Cierre de liquidación'),
               ('ajuste', 'Ajuste / compensación'), ('prueba', 'Prueba'), ('otro', 'Otro')]

    fecha = models.DateField()
    tipo = models.CharField(max_length=6, choices=TIPOS, default='FAC A')
    numero = models.CharField('N° de comprobante', max_length=40)
    importe = models.DecimalField('Importe total', max_digits=16, decimal_places=2)
    motivo = models.CharField('Motivo de emisión', max_length=10, choices=MOTIVOS, default='servicio')
    observaciones = models.CharField(max_length=200, blank=True)
    anulado = models.BooleanField(default=False)
    ref_planilla = models.CharField('Referencia en la planilla', max_length=20, blank=True)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha', 'id']
        verbose_name = 'comprobante'

    def __str__(self):
        return f'{self.tipo} {self.numero}'

    @property
    def en_negro(self):
        """Factura (o NC) M: sin IVA, se cobra en efectivo sin factura (decisión de la contadora)."""
        return self.tipo in COMPROBANTES_EN_NEGRO

    def imputado(self):
        return _suma(self.imputaciones.all())

    def sin_imputar(self):
        return self.importe - self.imputado()

    def anticipos(self):
        """Imputaciones a liquidaciones que todavía no estaban cerradas cuando se emitió el comprobante."""
        resultado = []
        for imp in self.imputaciones.select_related('liquidacion'):
            liq = imp.liquidacion
            if self.fecha < liq.periodo:
                resultado.append((imp, 'antes del mes liquidado'))
            elif liq.fecha_cierre and self.fecha < liq.fecha_cierre:
                resultado.append((imp, 'antes del cierre'))
        return resultado


class ImputacionComprobante(models.Model):
    comprobante = models.ForeignKey(Comprobante, on_delete=models.CASCADE, related_name='imputaciones')
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.PROTECT, related_name='imputaciones_comprobantes',
                                    verbose_name='Liquidación')
    servicio = models.ForeignKey(ServicioMAT, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='imputaciones_comprobantes', verbose_name='Salida')
    parte = models.CharField(max_length=10, choices=PARTES)
    importe = models.DecimalField(max_digits=16, decimal_places=2)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['liquidacion__periodo', 'id']


class Pago(models.Model):
    MEDIOS = [('efectivo', 'Efectivo'), ('transferencia', 'Transferencia'), ('cheque', 'Cheque'), ('otro', 'Otro')]
    RECIBOS = [('REC A', 'Recibo A'), ('REC M', 'Recibo M'), ('', 'Sin recibo')]

    fecha = models.DateField()
    medio = models.CharField('Forma de pago', max_length=14, choices=MEDIOS)
    moneda = models.CharField(max_length=3, choices=[('ARS', 'Pesos'), ('USD', 'Dólares')], default='ARS')
    importe_origen = models.DecimalField('Importe', max_digits=16, decimal_places=2)
    tipo_cambio = models.DecimalField('Tipo de cambio', max_digits=12, decimal_places=4, default=1)
    banco_referencia = models.CharField('Banco / referencia', max_length=120, blank=True)
    tipo_recibo = models.CharField('Tipo de recibo', max_length=6, choices=RECIBOS, blank=True)
    numero_recibo = models.CharField('N° de recibo', max_length=40, blank=True)
    comprobante = models.ForeignKey(Comprobante, null=True, blank=True, on_delete=models.SET_NULL, related_name='pagos',
        verbose_name='Factura que paga', help_text='La factura con la que se corresponde este pago (si la hay).')
    observaciones = models.CharField(max_length=200, blank=True)
    anulado = models.BooleanField(default=False)
    ref_planilla = models.CharField('Referencia en la planilla', max_length=20, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')

    class Meta:
        ordering = ['fecha', 'id']
        verbose_name = 'pago recibido'
        verbose_name_plural = 'pagos recibidos'

    def __str__(self):
        return f'Pago {self.fecha:%d/%m/%Y} {self.get_medio_display()} $ {self.importe_ars}'

    @property
    def en_negro(self):
        """Recibo M o pago de una factura M: va a la parte en efectivo sin factura."""
        return self.tipo_recibo == 'REC M' or bool(self.comprobante_id and self.comprobante.en_negro)

    @property
    def importe_ars(self):
        return redondear(self.importe_origen * (self.tipo_cambio if self.moneda == 'USD' else 1))

    def imputado(self):
        return _suma(self.imputaciones.all())

    def sin_imputar(self):
        return self.importe_ars - self.imputado()


class ImputacionPago(models.Model):
    pago = models.ForeignKey(Pago, on_delete=models.CASCADE, related_name='imputaciones')
    liquidacion = models.ForeignKey(Liquidacion, on_delete=models.PROTECT, related_name='imputaciones_pagos',
                                    verbose_name='Liquidación')
    servicio = models.ForeignKey(ServicioMAT, null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name='imputaciones_pagos', verbose_name='Salida',
                                 help_text='Vacío = a cuenta del mes (se reparte entre las salidas de la más vieja a la más nueva).')
    parte = models.CharField(max_length=10, choices=PARTES)
    importe = models.DecimalField(max_digits=16, decimal_places=2)
    observaciones = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['liquidacion__periodo', 'id']
