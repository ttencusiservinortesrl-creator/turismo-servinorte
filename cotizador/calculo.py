"""Cálculo del costo de un viaje, igual que la planilla "COTIZACIONES 2026".

Cada ítem se calcula por vehículo y después se multiplica por la cantidad de vehículos.
"""
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from django.utils import timezone

CERO = Decimal('0')
CIEN = Decimal('100')


def redondear(valor, decimales='0.01'):
    return Decimal(valor).quantize(Decimal(decimales), rounding=ROUND_HALF_UP)


def _txt(valor):
    """Número para los textos de ayuda: 2500.00 -> 2.500 ; 10.50 -> 10,5"""
    valor = Decimal(valor).normalize()
    entero, _, dec = f'{valor:f}'.partition('.')
    entero = f'{int(entero):,}'.replace(',', '.')
    return f'{entero},{dec}' if dec else entero


def _dec(valor):
    if valor in (None, ''):
        return CERO
    return Decimal(str(valor))


def proyeccion(p, datos):
    """Si el viaje sale más adelante, cuánto subirían los costos hasta esa fecha por inflación.
    Devuelve None si no corresponde proyectar."""
    fecha, salida = datos.get('fecha'), datos.get('salida')
    tasa = _dec(datos.get('inflacion_mensual'))
    if not datos.get('proyectar_inflacion') or not fecha or not salida or tasa <= 0:
        return None
    if isinstance(salida, datetime):
        salida = timezone.localtime(salida).date() if timezone.is_aware(salida) else salida.date()
    dias = (salida - fecha).days
    if dias <= p.proyectar_desde_dias:
        return None
    meses = redondear(Decimal(dias) / 30, '0.1')
    factor = (1 + tasa / CIEN) ** meses
    return {'dias': dias, 'meses': meses, 'tasa': tasa, 'factor': factor,
            'porcentaje': redondear((factor - 1) * CIEN, '0.1')}


NOMBRE_IMPUESTOS = 'Impuestos sobre la venta'


def _excluidos(datos):
    """Nombres de los ítems destildados (texto separado por | o lista)."""
    valor = datos.get('items_excluidos') or datos.get('excluidos') or ''
    if isinstance(valor, str):
        valor = valor.split('|')
    return [v.strip() for v in valor if v and v.strip()]


def _lineas(datos):
    """Vehículos de la cotización: [{'vehiculo', 'cantidad', 'choferes'}]. Acepta también el formato
    viejo de un solo vehículo (vehiculo, cantidad_vehiculos, choferes)."""
    if 'lineas' in datos:
        return [l for l in datos['lineas'] if l.get('vehiculo')]
    return [{'vehiculo': datos.get('vehiculo'), 'cantidad': datos.get('cantidad_vehiculos'),
             'choferes': datos.get('choferes')}]


def calcular(p, datos):
    """p: Parametros. datos: dict con km_servicio, km_vacios, dias, noches, viaticos_por_chofer, habitaciones,
    lineas (vehículos con cantidad y choferes), incluye_hotel, incluye_estacionamiento, incluye_lavadero,
    peaje, otros_gastos, tarifa_neta, fecha, salida, proyectar_inflacion, inflacion_mensual."""
    km_totales = _dec(datos.get('km_servicio')) + _dec(datos.get('km_vacios'))
    dias = _dec(datos.get('dias'))
    noches = _dec(datos.get('noches'))
    lineas = _lineas(datos)
    varias = len(lineas) > 1

    sueldo_dia = p.valor_dia_turismo * p.factor_sueldo_conductor
    divisor = Decimal(p.divisor_prorrateo or 1)
    flota = Decimal(p.vehiculos_flota or 1)
    vida_util = Decimal(p.vida_util_meses or 1)

    # Cada ítem se calcula por vehículo y se suma entre las líneas (orden fijo para mostrar).
    importes, detalles = {}, {}
    capacidad = 0
    for linea in lineas:
        vehiculo = linea.get('vehiculo')
        cantidad = max(_dec(linea.get('cantidad')), Decimal(1))
        choferes = _dec(linea.get('choferes'))
        rendimiento = vehiculo.rendimiento_km_litro if vehiculo and vehiculo.rendimiento_km_litro else Decimal(3)
        capacidad += (vehiculo.capacidad if vehiculo else 0) * int(cantidad)
        items = [
            ('Cargas sociales', sueldo_dia * p.porcentaje_cargas_sociales / CIEN * dias * choferes,
             f'{_txt(p.porcentaje_cargas_sociales)}% del sueldo × {_txt(dias)} días × {_txt(choferes)} chofer/es'),
            ('Sueldo de conductor', sueldo_dia * dias * choferes + p.no_remunerativo_mensual / 30 * dias * choferes,
             f'(sueldo diario + no remunerativo) × {_txt(dias)} días × {_txt(choferes)} chofer/es'),
            ('Gastos de administración', p.gastos_admin_mensuales / divisor, f'gastos mensuales ÷ {_txt(divisor)}'),
            ('Hotel', p.hotel_por_noche * noches * _dec(datos.get('habitaciones')) if datos.get('incluye_hotel') else CERO,
             f'{_txt(noches)} noches × {datos.get("habitaciones") or 0} habitación/es' if datos.get('incluye_hotel') else 'no incluido'),
            ('Viáticos', p.viatico_por_unidad * _dec(datos.get('viaticos_por_chofer')) * choferes,
             f'{datos.get("viaticos_por_chofer") or 0} viáticos × {_txt(choferes)} chofer/es'),
            ('Peajes', _dec(datos.get('peaje')), ''),
            ('Combustible', p.precio_combustible * km_totales / rendimiento,
             f'{_txt(km_totales)} km ÷ {_txt(rendimiento)} km/l × ${_txt(p.precio_combustible)}'),
            ('Depreciación', (p.valor_adquisicion - p.valor_residual) / vida_util / divisor,
             f'(valor - residual) ÷ {_txt(vida_util)} meses ÷ {_txt(divisor)}'),
            ('Estacionamiento', p.estacionamiento if datos.get('incluye_estacionamiento') else CERO,
             '' if datos.get('incluye_estacionamiento') else 'no incluido'),
            ('Lavadero', p.lavadero if datos.get('incluye_lavadero') else CERO,
             '' if datos.get('incluye_lavadero') else 'no incluido'),
            ('Seguro obligatorio', p.seguro_mensual_flota / flota / 30 * dias, f'seguro por vehículo ÷ 30 × {_txt(dias)} días'),
            ('Insumos de limpieza', p.insumos_limpieza, ''),
        ]
        for nombre, valor, detalle in items:
            importes[nombre] = importes.get(nombre, CERO) + redondear(valor * cantidad)
            if varias:
                nombre_linea = f'{_txt(cantidad)} × {vehiculo.nombre}' if vehiculo else ''
                detalle = f'{nombre_linea}: {detalle}' if detalle else nombre_linea
            elif cantidad > 1:
                detalle = f'{detalle} × {_txt(cantidad)} vehículos' if detalle else f'× {_txt(cantidad)} vehículos'
            detalles.setdefault(nombre, []).append(detalle)
    items = [{'nombre': n, 'importe': v, 'detalle': ' | '.join(d for d in detalles[n] if d)} for n, v in importes.items()]
    items.append({'nombre': 'Otros gastos', 'importe': redondear(_dec(datos.get('otros_gastos'))), 'detalle': 'total del viaje'})
    costo_hoy = sum((i['importe'] for i in items), CERO)
    inflacion = proyeccion(p, datos)
    if inflacion:
        inflacion['costo_hoy'] = costo_hoy
        items.append({'nombre': 'Ajuste por inflación', 'importe': redondear(costo_hoy * (inflacion['factor'] - 1)),
                      'detalle': f"{_txt(inflacion['meses'])} meses al {_txt(inflacion['tasa'])}% mensual "
                                 f"= +{_txt(inflacion['porcentaje'])}% hasta la salida",
                      'inflacion': True})
        del inflacion['factor']
    # Ítems que el usuario destildó: se muestran pero no se suman.
    excluidos = set(_excluidos(datos))
    for item in items:
        item['excluido'] = item['nombre'] in excluidos
    costo = sum((i['importe'] for i in items if not i['excluido']), CERO)  # costo operativo
    costo_km = costo / km_totales if km_totales else CERO

    # Impuestos sobre la venta (TISSH + AMT + IIBB): son un % del precio sin IVA. Para que el margen quede
    # limpio después de impuestos, cada precio se calcula como costo × (1 + margen) ÷ (1 − tasa).
    tasa_impuestos = (p.porcentaje_tissh + p.porcentaje_amt + p.porcentaje_iibb) / CIEN
    impuestos_excluidos = NOMBRE_IMPUESTOS in excluidos
    if impuestos_excluidos or tasa_impuestos >= 1:
        tasa_aplicada = CERO
    else:
        tasa_aplicada = tasa_impuestos
    divisor_impuestos = 1 - tasa_aplicada

    def fila(nombre, total, valor_km=None):
        total = redondear(total)
        impuestos = redondear(total * tasa_aplicada)
        ganancia = total - costo - impuestos
        iva = redondear(total * p.porcentaje_iva / CIEN)
        return {
            'nombre': nombre,
            'valor_km': redondear(valor_km if valor_km is not None else (total / km_totales if km_totales else CERO)),
            'total': total,
            'impuestos': impuestos,
            'ganancia': ganancia,
            'perdida': ganancia < 0,
            'rentabilidad': redondear(ganancia / total * CIEN, '0.1') if total else CERO,
            'por_pax': redondear(total / capacidad) if capacidad else CERO,
            'iva': iva,
            'bruto': total + iva,
        }

    # "Costo" = precio mínimo para no perder: cubre el costo operativo y los impuestos de ese precio.
    costo_con_impuestos_km = costo_km / divisor_impuestos
    filas = [fila('Costo', costo / divisor_impuestos, costo_con_impuestos_km)]
    for nombre, margen in (('Mínimo', p.margen_minimo), ('Intermedio', p.margen_intermedio),
                           ('Mercado', p.margen_mercado), ('Óptimo', p.margen_optimo)):
        valor_km = redondear(costo_km * (1 + margen / CIEN) / divisor_impuestos, '1')
        f = fila(f'{nombre} ({_txt(margen)}%)', valor_km * km_totales, valor_km)
        f['sugerido'] = redondear(f['total'] / 10000, '1') * 10000 if f['total'] else CERO
        filas.append(f)
    filas.append(fila(f'Ref. ${_txt(p.precio_referencia_km)}/km', p.precio_referencia_km * km_totales,
                      p.precio_referencia_km))

    tarifa = _dec(datos.get('tarifa_neta'))
    final = fila('Tarifa final', tarifa) if tarifa else None

    # En el detalle, los impuestos se muestran sobre la tarifa final (o sobre el precio mínimo si todavía no hay).
    base = final or filas[0]
    detalle_impuestos = (f'{_txt(p.porcentaje_tissh)}% TISSH + {_txt(p.porcentaje_amt)}% AMT + '
                         f'{_txt(p.porcentaje_iibb)}% IIBB = {_txt(tasa_impuestos * CIEN)}% de '
                         f'${_txt(base["total"])} ({"tarifa final" if final else "precio mínimo"})')
    items.append({'nombre': NOMBRE_IMPUESTOS, 'importe': redondear(base['total'] * tasa_impuestos),
                  'detalle': detalle_impuestos, 'excluido': impuestos_excluidos, 'impuesto': True})
    costo_total = costo + (CERO if impuestos_excluidos else items[-1]['importe'])

    return {
        'km_totales': km_totales,
        'capacidad': capacidad,
        'items': items,
        'costo_operativo': redondear(costo),
        'costo': redondear(costo_total),
        'costo_km': redondear(costo_total / km_totales) if km_totales else CERO,
        'tasa_impuestos': redondear(tasa_impuestos * CIEN),
        'filas': filas,
        'final': final,
        'inflacion': inflacion,
        'excluidos': sorted(excluidos),
    }


def para_guardar(resultado, p):
    """Versión del cálculo que se guarda en la cotización (texto, para JSON)."""
    def limpio(valor):
        if isinstance(valor, Decimal):
            return str(valor)
        if isinstance(valor, dict):
            return {k: limpio(v) for k, v in valor.items()}
        if isinstance(valor, list):
            return [limpio(v) for v in valor]
        return valor

    parametros = {f.verbose_name: str(getattr(p, f.name)) for f in p._meta.concrete_fields
                  if f.get_internal_type() in ('DecimalField', 'PositiveIntegerField')}
    return limpio({**resultado, 'parametros': parametros})
