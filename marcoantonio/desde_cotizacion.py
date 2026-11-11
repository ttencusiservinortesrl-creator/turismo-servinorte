"""Pasar una cotización aceptada a una salida de Marco Antonio."""
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import ServicioMAT


def es_cliente_mat(cliente):
    nombre = cliente.nombre.upper()
    return 'MARCO ANTONIO' in nombre or nombre.strip() in ('MAT', 'M.A.T.')


def tarifas_sugeridas(cot):
    """Mínima, intermedia y óptima según los márgenes del cálculo de la cotización (sin IVA, redondeadas)."""
    sugeridas = {'minima': Decimal(0), 'intermedia': Decimal(0), 'optima': Decimal(0)}
    # Las cotizaciones nuevas dicen "Mínimo (20%)"; las primeras, "Margen mínimo (20%)"
    claves = {'mínimo': 'minima', 'minimo': 'minima', 'intermedio': 'intermedia', 'óptimo': 'optima', 'optimo': 'optima'}
    for fila in cot.detalle.get('filas', []):
        nombre = str(fila.get('nombre', '')).split(' (')[0].lower().replace('margen ', '').strip()
        if nombre in claves:
            try:
                sugeridas[claves[nombre]] = Decimal(str(fila.get('sugerido') or fila.get('total') or 0))
            except InvalidOperation:
                pass
    return sugeridas


def leer_tarifas(post):
    """Toma del formulario las tarifas y cuál se vendió. Devuelve (datos, error)."""
    datos = {}
    for c in ('tarifa_minima', 'tarifa_intermedia', 'tarifa_optima', 'tarifa_otra'):
        texto = (post.get(c) or '').strip().replace('$', '').replace(' ', '')
        if ',' in texto:  # formato argentino: 1.700.000,50
            texto = texto.replace('.', '').replace(',', '.')
        try:
            datos[c] = Decimal(texto) if texto else Decimal(0)
        except InvalidOperation:
            return None, 'Revisá los importes de las tarifas: hay uno que no es un número.'
    elegida = post.get('tarifa_elegida', 'otra')
    if elegida not in ('minima', 'intermedia', 'optima', 'otra'):
        elegida = 'otra'
    datos['tarifa_elegida'] = elegida
    if datos[f'tarifa_{elegida}'] <= 0:
        return None, 'La tarifa vendida no tiene importe: completala o elegí otra.'
    if elegida != 'otra':
        datos['tarifa_otra'] = None
    return datos, ''


def datos_de(cot):
    fecha = timezone.localtime(cot.salida).date()
    unidades = ', '.join(a.unidad for a in cot.asignaciones.all())
    unidad = cot.vehiculos_texto + (f' (unidad {unidades})' if unidades else '')
    obs = f'COT {cot.numero}'
    if cot.colaciones_cantidad:
        obs += f' · incluye {cot.colaciones_cantidad} colaciones cotizadas'
    return {'fecha': fecha, 'unidad': unidad[:60], 'servicio': (cot.itinerario or cot.paradas)[:200],
            'tarifa_elegida': 'otra', 'tarifa_otra': cot.tarifa_neta, 'observaciones': obs[:200]}


@transaction.atomic
def crear_salida(cot, tarifas=None):
    """Crea la salida en el mes que corresponde (lo crea si no existe). Devuelve la salida.
    `tarifas`: lo que devuelve leer_tarifas (si no, se vende al precio de la cotización)."""
    from .views import _liquidacion_del_mes
    existente = ServicioMAT.objects.filter(cotizacion=cot).first()
    if existente:
        return existente
    datos = datos_de(cot)
    if tarifas:
        datos.update(tarifas)
    return ServicioMAT.objects.create(liquidacion=_liquidacion_del_mes(datos['fecha']), cotizacion=cot, **datos)


def actualizar_precio(cot, anterior):
    """Si cambia el precio de la cotización, la salida lo sigue, solo si estaba vendida a ese mismo precio
    (si en Marco Antonio se eligió o se tipeó otra tarifa, no se toca)."""
    sal = ServicioMAT.objects.filter(cotizacion=cot, tarifa_elegida='otra', tarifa_otra=anterior).first()
    if sal and anterior != cot.tarifa_neta:
        sal.tarifa_otra = cot.tarifa_neta
        sal.save(update_fields=['tarifa_otra'])


def quitar_salida(cot):
    """Al anular o volver atrás la cotización: borra la salida si no tiene nada cargado.
    Devuelve un texto para avisar, o '' si no había salida."""
    sal = ServicioMAT.objects.filter(cotizacion=cot).first()
    if not sal:
        return ''
    if sal.insumos.exists() or sal.imputaciones_pagos.exists() or sal.imputaciones_comprobantes.exists():
        sal.cotizacion = None
        sal.save(update_fields=['cotizacion'])
        return (f'La salida de Marco Antonio del {sal.fecha:%d/%m/%Y} tiene insumos o pagos cargados: '
                f'no la borré, revisala en Marco Antonio.')
    sal.delete()
    return f'Se quitó la salida de Marco Antonio del {sal.fecha:%d/%m/%Y}.'
