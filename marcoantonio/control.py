"""Números del tablero de Marco Antonio Tours: cuenta corriente, saldos por liquidación y controles."""
from decimal import Decimal

from .models import EFECTIVO, FACTURADA, PARTES, Comprobante, Liquidacion, Pago

UMBRAL = Decimal('0.01')


def cuenta_corriente():
    """Saldo de MAT con las liquidaciones cerradas (las abiertas se muestran aparte, como "en curso")."""
    liquidaciones = list(Liquidacion.objects.prefetch_related('servicios', 'entregas__articulo'))
    cerradas = [l for l in liquidaciones if l.cerrada]
    abiertas = [l for l in liquidaciones if not l.cerrada]
    pagos = list(Pago.objects.filter(anulado=False))
    liquidado = {parte: sum((l.importe(parte) for l in cerradas), Decimal(0)) for parte, _ in PARTES}
    recibido = sum((p.importe_ars for p in pagos), Decimal(0))
    recibido_por_medio = {}
    for p in pagos:
        recibido_por_medio[p.get_medio_display()] = recibido_por_medio.get(p.get_medio_display(), Decimal(0)) + p.importe_ars
    total_liquidado = liquidado[FACTURADA] + liquidado[EFECTIVO]
    return {
        'liquidado': liquidado, 'total_liquidado': total_liquidado, 'recibido': recibido,
        'recibido_por_medio': recibido_por_medio, 'saldo': total_liquidado - recibido,
        'en_curso': sum((l.total() for l in abiertas), Decimal(0)), 'abiertas': abiertas,
    }


def filas_liquidaciones():
    filas = []
    for liq in Liquidacion.objects.prefetch_related('servicios', 'entregas__articulo'):
        filas.append({'liq': liq, 'partes': liq.resumen(), 'total': liq.total()})
    return filas


def controles():
    """Lo que hay que mirar: facturas anticipadas, pagos y comprobantes sin imputar, transferencias sin factura,
    lo liquidado sin comprobante y los saldos a cobrar."""
    comprobantes = list(Comprobante.objects.filter(anulado=False).prefetch_related('imputaciones__liquidacion'))
    pagos = list(Pago.objects.filter(anulado=False).prefetch_related('imputaciones'))
    anticipados = [(c, imp, motivo) for c in comprobantes for imp, motivo in c.anticipos()]
    comprobantes_sin_imputar = [(c, c.sin_imputar()) for c in comprobantes if c.sin_imputar() > UMBRAL]
    pagos_sin_imputar = [(p, p.sin_imputar()) for p in pagos if p.sin_imputar() > UMBRAL]
    transferencias_sin_factura = [p for p in pagos if p.medio == 'transferencia' and not p.comprobante_id]
    pendiente_facturar, a_cobrar = [], []
    for liq in Liquidacion.objects.filter(fecha_cierre__isnull=False).prefetch_related('servicios', 'entregas__articulo'):
        falta = liq.sin_comprobante(FACTURADA)
        if falta > UMBRAL:
            pendiente_facturar.append((liq, falta))
        for parte, nombre in PARTES:
            saldo = liq.saldo(parte)
            if saldo > UMBRAL:
                a_cobrar.append((liq, nombre, saldo))
    return {
        'anticipados': anticipados, 'comprobantes_sin_imputar': comprobantes_sin_imputar,
        'pagos_sin_imputar': pagos_sin_imputar, 'transferencias_sin_factura': transferencias_sin_factura,
        'pendiente_facturar': pendiente_facturar, 'a_cobrar': a_cobrar,
        'total': len(anticipados) + len(comprobantes_sin_imputar) + len(pagos_sin_imputar)
                 + len(transferencias_sin_factura) + len(pendiente_facturar),
    }
