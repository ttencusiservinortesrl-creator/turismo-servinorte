"""Números para la pantalla de estadísticas: aceptación, motivos de rechazo, destinos, clientes y vehículos."""
from collections import defaultdict
from decimal import Decimal

from .models import Cotizacion

MESES_CORTOS = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']


def _normalizar(texto):
    """'  orán, salta ' -> 'Orán, Salta' (para agrupar destinos y motivos escritos distinto)."""
    texto = ' '.join(texto.split()).strip(' .')
    return texto[:1].upper() + texto[1:] if texto else ''


class _Agrupador:
    """Agrupa textos escritos distinto ("orán, salta" y "Orán, Salta") y muestra la forma mejor escrita."""
    def __init__(self):
        self.nombres = {}

    def __call__(self, texto):
        nombre = _normalizar(texto)
        clave = nombre.casefold()
        actual = self.nombres.get(clave)
        mayusculas = lambda t: sum(ch.isupper() for ch in t)
        if actual is None or mayusculas(nombre) > mayusculas(actual):
            self.nombres[clave] = nombre
        return clave


def _porcentaje(parte, total):
    return round(Decimal(parte) * 100 / total, 1) if total else Decimal(0)


def _con_barras(filas, clave):
    maximo = max((f[clave] for f in filas), default=0)
    for f in filas:
        f['barra'] = round(float(f[clave]) * 100 / float(maximo)) if maximo else 0
    return filas


def calcular(desde, hasta):
    cotizaciones = list(Cotizacion.objects.filter(fecha__range=(desde, hasta))
                        .select_related('cliente').prefetch_related('lineas__vehiculo'))
    aceptadas = [c for c in cotizaciones if c.estado == Cotizacion.ACEPTADA]
    rechazadas = [c for c in cotizaciones if c.estado == Cotizacion.RECHAZADA]
    pendientes = [c for c in cotizaciones if c.estado == Cotizacion.PENDIENTE]
    respondidas = len(aceptadas) + len(rechazadas)
    vendido = sum((c.tarifa_neta for c in aceptadas), Decimal(0))
    ganancia = sum((Decimal(c.detalle.get('final', {}).get('ganancia', 0) or 0) for c in aceptadas), Decimal(0))

    resumen = {
        'total': len(cotizaciones), 'aceptadas': len(aceptadas), 'rechazadas': len(rechazadas),
        'pendientes': len(pendientes),
        'tasa_aceptacion': _porcentaje(len(aceptadas), respondidas),
        'cotizado': sum((c.tarifa_neta for c in cotizaciones), Decimal(0)),
        'vendido': vendido, 'ganancia': ganancia,
        'rentabilidad': _porcentaje(ganancia, vendido),
        'promedio': (vendido / len(aceptadas)) if aceptadas else Decimal(0),
    }

    # Por mes (de la fecha de la cotización)
    por_mes = defaultdict(lambda: {'cotizadas': 0, 'aceptadas': 0, 'vendido': Decimal(0)})
    for c in cotizaciones:
        m = por_mes[(c.fecha.year, c.fecha.month)]
        m['cotizadas'] += 1
        if c.estado == Cotizacion.ACEPTADA:
            m['aceptadas'] += 1
            m['vendido'] += c.tarifa_neta
    meses = [{'mes': f'{MESES_CORTOS[mes - 1]} {anio}', **datos} for (anio, mes), datos in sorted(por_mes.items())]
    _con_barras(meses, 'cotizadas')
    maximo = max((m['cotizadas'] for m in meses), default=0)
    for m in meses:
        m['barra_aceptadas'] = round(m['aceptadas'] * 100 / maximo) if maximo else 0

    # Motivos de rechazo
    motivos, nombre_motivo = defaultdict(int), _Agrupador()
    for c in rechazadas:
        motivos[nombre_motivo(c.motivo_rechazo or 'Sin motivo anotado')] += 1
    motivos = _con_barras([{'motivo': nombre_motivo.nombres[k], 'cantidad': v, 'porcentaje': _porcentaje(v, len(rechazadas))}
                           for k, v in sorted(motivos.items(), key=lambda x: -x[1])], 'cantidad')

    # Destinos (cada renglón de "paradas")
    destinos, nombre_destino = defaultdict(lambda: {'pedidos': 0, 'aceptados': 0, 'vendido': Decimal(0)}), _Agrupador()
    for c in cotizaciones:
        for parada in {nombre_destino(p) for p in c.paradas.splitlines() if p.strip()}:
            d = destinos[parada]
            d['pedidos'] += 1
            if c.estado == Cotizacion.ACEPTADA:
                d['aceptados'] += 1
                d['vendido'] += c.tarifa_neta
    destinos = [{'destino': nombre_destino.nombres[k], **v, 'tasa': _porcentaje(v['aceptados'], v['pedidos'])}
                for k, v in sorted(destinos.items(), key=lambda x: (-x[1]['pedidos'], x[0]))][:15]
    _con_barras(destinos, 'pedidos')

    # Clientes que más compraron
    clientes = defaultdict(lambda: {'cotizaciones': 0, 'aceptadas': 0, 'vendido': Decimal(0)})
    for c in cotizaciones:
        d = clientes[c.cliente]
        d['cotizaciones'] += 1
        if c.estado == Cotizacion.ACEPTADA:
            d['aceptadas'] += 1
            d['vendido'] += c.tarifa_neta
    clientes = [{'cliente': k, **v} for k, v in sorted(clientes.items(), key=lambda x: (-x[1]['vendido'], -x[1]['cotizaciones']))][:10]
    _con_barras(clientes, 'vendido')

    # Vehículos en los viajes vendidos
    vehiculos = defaultdict(int)
    for c in aceptadas:
        for linea in c.lineas.all():
            vehiculos[linea.vehiculo.nombre] += linea.cantidad
    vehiculos = _con_barras([{'vehiculo': k, 'cantidad': v} for k, v in sorted(vehiculos.items(), key=lambda x: -x[1])],
                            'cantidad')

    return {'resumen': resumen, 'meses': meses, 'motivos': motivos, 'destinos': destinos,
            'clientes': clientes, 'vehiculos': vehiculos}
