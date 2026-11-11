from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import control, excel, importador
from .forms import (ArticuloForm, ComprobanteForm, EntregaForm, ImportarForm, ImputacionesComprobanteFormSet,
                    ImputacionesPagoFormSet, LiquidacionForm, PagoForm, SalidaForm, ServicioForm)
from .models import ESTADOS_PAGO, PARTES, Articulo, Comprobante, EntregaInsumo, Liquidacion, Pago, ServicioMAT


def mat(vista):
    """Solo usuarios con permiso para ver la sección de Marco Antonio."""
    return login_required(permission_required('marcoantonio.view_liquidacion', raise_exception=True)(vista))


@mat
def tablero(request):
    return render(request, 'marcoantonio/tablero.html', {
        'cc': control.cuenta_corriente(), 'filas': control.filas_liquidaciones(), 'controles': control.controles(),
        'partes': PARTES})


# ---------- Liquidaciones ----------

@mat
def liquidacion_nueva(request):
    form = LiquidacionForm(request.POST or None, initial={'mes': timezone.localdate().replace(day=1)})
    if request.method == 'POST' and form.is_valid():
        liq = form.save()
        messages.success(request, f'Liquidación {liq.nombre} creada.')
        return redirect('marcoantonio:liquidacion', liq.pk)
    return render(request, 'marcoantonio/form.html', {'form': form, 'titulo': 'Nueva liquidación'})


@mat
def liquidacion_editar(request, pk):
    liq = get_object_or_404(Liquidacion, pk=pk)
    form = LiquidacionForm(request.POST or None, instance=liq)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Liquidación actualizada.')
        return redirect('marcoantonio:liquidacion', pk)
    return render(request, 'marcoantonio/form.html', {'form': form, 'titulo': f'Editar liquidación {liq.nombre}',
                                                      'volver': liq})


def _planilla_insumos(liq):
    """Grilla como la de la planilla: artículo × día, con total y precio."""
    entregas = list(liq.entregas.select_related('articulo'))
    dias = sorted({e.fecha for e in entregas})
    secciones = {}
    for e in entregas:
        art = e.articulo
        seccion = secciones.setdefault(art.get_categoria_display(), {})
        fila = seccion.setdefault(art.pk, {'articulo': art, 'por_dia': {}, 'cantidad': 0, 'total': 0})
        fila['por_dia'][e.fecha] = fila['por_dia'].get(e.fecha, 0) + e.cantidad
        fila['cantidad'] += e.cantidad
        fila['total'] += e.total
    resultado = []
    for nombre, filas in secciones.items():
        filas = sorted(filas.values(), key=lambda f: f['articulo'].codigo)
        for f in filas:
            f['celdas'] = [f['por_dia'].get(d, '') for d in dias]
        resultado.append({'nombre': nombre, 'filas': filas, 'total': sum(f['total'] for f in filas)})
    return dias, resultado


@mat
def liquidacion(request, pk):
    liq = get_object_or_404(Liquidacion.objects.prefetch_related('servicios', 'entregas__articulo'), pk=pk)
    dias, secciones = _planilla_insumos(liq)
    suma_detalle = liq.total_servicios() + liq.total_agua() + liq.total_insumos()
    return render(request, 'marcoantonio/liquidacion.html', {
        'liq': liq, 'partes': liq.resumen(), 'dias': dias, 'secciones': secciones, 'suma_detalle': suma_detalle,
        'insumos_colacion': liq.total_insumos('colacion'), 'insumos_limpieza': liq.total_insumos('limpieza'),
        'insumos_otros': liq.total_insumos('otro'),
        'diferencia_detalle': (liq.neto_manual - suma_detalle) if liq.neto_manual is not None and (liq.servicios.exists() or liq.entregas.exists()) else None,
        'servicio_form': ServicioForm(initial={'fecha': liq.periodo}),
        'entrega_form': EntregaForm(initial={'fecha': timezone.localdate() if timezone.localdate().replace(day=1) == liq.periodo else liq.periodo}),
        'filas_salidas': _filas_salidas(liq.servicios.select_related('liquidacion').prefetch_related('insumos__articulo')),
        'resto_mes': {parte: liq.resto_del_mes(parte) for parte, _ in PARTES},
        'sobrante_pagos': liq.reparto_pagos()[None],
        'estados': ESTADOS_PAGO,
        'imputaciones_pagos': liq.imputaciones_pagos.select_related('pago', 'servicio').order_by('pago__fecha'),
        'imputaciones_comprobantes': liq.imputaciones_comprobantes.select_related('comprobante').order_by('comprobante__fecha'),
    })


@mat
@require_POST
def liquidacion_cerrar(request, pk):
    liq = get_object_or_404(Liquidacion, pk=pk)
    if liq.cerrada:
        liq.fecha_cierre = None
        messages.success(request, f'Liquidación {liq.nombre} reabierta: deja de contar en la cuenta corriente hasta que la cierres.')
    else:
        liq.fecha_cierre = timezone.localdate()
        messages.success(request, f'Liquidación {liq.nombre} cerrada: ya cuenta en la cuenta corriente.')
    liq.save(update_fields=['fecha_cierre'])
    return redirect('marcoantonio:liquidacion', pk)


@mat
@require_POST
def servicio_guardar(request, pk, servicio_pk=None):
    liq = get_object_or_404(Liquidacion, pk=pk)
    servicio = get_object_or_404(ServicioMAT, pk=servicio_pk, liquidacion=liq) if servicio_pk else ServicioMAT(liquidacion=liq)
    form = ServicioForm(request.POST, instance=servicio)
    if form.is_valid():
        form.save()
        messages.success(request, 'Servicio guardado.')
    else:
        messages.error(request, 'No se guardó el servicio: ' + ' '.join(e for es in form.errors.values() for e in es))
    return redirect('marcoantonio:liquidacion', pk)


@mat
def servicio_editar(request, pk, servicio_pk):
    liq = get_object_or_404(Liquidacion, pk=pk)
    servicio = get_object_or_404(ServicioMAT, pk=servicio_pk, liquidacion=liq)
    form = ServicioForm(request.POST or None, instance=servicio)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Servicio actualizado.')
        return redirect('marcoantonio:liquidacion', pk)
    return render(request, 'marcoantonio/form.html', {'form': form, 'titulo': f'Servicio del {servicio.fecha:%d/%m}', 'volver': liq})


@mat
@require_POST
def servicio_borrar(request, pk, servicio_pk):
    get_object_or_404(ServicioMAT, pk=servicio_pk, liquidacion_id=pk).delete()
    messages.success(request, 'Servicio borrado.')
    return redirect('marcoantonio:liquidacion', pk)


@mat
@require_POST
def entrega_guardar(request, pk):
    liq = get_object_or_404(Liquidacion, pk=pk)
    form = EntregaForm(request.POST, instance=EntregaInsumo(liquidacion=liq))
    if form.is_valid():
        e = form.save()
        messages.success(request, f'Entrega cargada: {e.cantidad:g} × {e.articulo.nombre}.')
    else:
        messages.error(request, 'No se cargó la entrega: ' + ' '.join(e for es in form.errors.values() for e in es))
    return redirect('marcoantonio:liquidacion', pk)


@mat
def entregas(request, pk):
    liq = get_object_or_404(Liquidacion, pk=pk)
    return render(request, 'marcoantonio/entregas.html', {'liq': liq, 'entregas': liq.entregas.select_related('articulo', 'servicio'),
                                                          'salidas': liq.servicios.all()})


@mat
@require_POST
def entrega_borrar(request, pk, entrega_pk):
    get_object_or_404(EntregaInsumo, pk=entrega_pk, liquidacion_id=pk).delete()
    messages.success(request, 'Entrega borrada.')
    return redirect('marcoantonio:entregas', pk)


# ---------- Salidas ----------

def _liquidacion_del_mes(fecha):
    """La liquidación del mes de esa fecha; si no existe, se crea con el % y el IVA de la última."""
    periodo = fecha.replace(day=1)
    liq = Liquidacion.objects.filter(periodo=periodo).first()
    if liq:
        return liq
    anterior = Liquidacion.objects.order_by('-periodo').first()
    datos = {}
    if anterior:
        datos = {'porcentaje_facturado': anterior.porcentaje_facturado, 'porcentaje_iva': anterior.porcentaje_iva,
                 'precio_agua': anterior.precio_agua}
    return Liquidacion.objects.create(periodo=periodo, **datos)


def _filas_salidas(salidas):
    """Cada salida con su estado de pago (el reparto se calcula una vez por mes)."""
    repartos, filas = {}, []
    for sal in salidas:
        if sal.liquidacion_id not in repartos:
            repartos[sal.liquidacion_id] = sal.liquidacion.reparto_pagos()
        filas.append({'salida': sal, 'pagos': sal.estado_pagos(repartos[sal.liquidacion_id])})
    return filas


@mat
def salidas(request):
    estado = request.GET.get('estado', 'pendientes')
    mes = request.GET.get('mes', '')
    lista = ServicioMAT.objects.select_related('liquidacion').prefetch_related(
        'insumos__articulo', 'liquidacion__servicios__insumos__articulo',
        'liquidacion__imputaciones_pagos__pago').order_by('-fecha', '-id')
    if mes:
        lista = lista.filter(liquidacion_id=mes)
    filas = _filas_salidas(lista)
    if estado == 'pendientes':
        filas = [f for f in filas if f['pagos']['estado'] in ('pendiente', 'parcial', 'sin_importe')]
    elif estado == 'pagadas':
        filas = [f for f in filas if f['pagos']['estado'] == 'pagada']
    return render(request, 'marcoantonio/salidas.html', {
        'filas': filas, 'estado': estado, 'mes': mes, 'meses': Liquidacion.objects.order_by('-periodo'),
        'estados': ESTADOS_PAGO,
        'saldo_total': sum((f['pagos']['saldo'] for f in filas), 0)})


@mat
def salida_nueva(request):
    form = SalidaForm(request.POST or None, initial={'fecha': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        salida = form.save(commit=False)
        salida.liquidacion = _liquidacion_del_mes(salida.fecha)
        salida.save()
        if salida.liquidacion.cerrada:
            messages.warning(request, f'Ojo: la liquidación de {salida.liquidacion.nombre} ya estaba cerrada.')
        messages.success(request, 'Salida cargada. Ahora podés agregar los insumos que llevó.')
        return redirect('marcoantonio:salida', salida.pk)
    return render(request, 'marcoantonio/form.html', {'form': form, 'titulo': 'Nueva salida'})


@mat
def salida(request, pk):
    sal = get_object_or_404(ServicioMAT.objects.select_related('liquidacion'), pk=pk)
    liq = sal.liquidacion
    imputaciones = [i for i in liq.imputaciones_pagos.select_related('pago') if i.servicio_id == sal.pk]
    return render(request, 'marcoantonio/salida.html', {
        'sal': sal, 'liq': liq, 'pagos': sal.estado_pagos(), 'estados': ESTADOS_PAGO,
        'insumos': sal.insumos.select_related('articulo'), 'imputaciones': imputaciones,
        'comprobantes': sal.imputaciones_comprobantes.select_related('comprobante'),
        'entrega_form': EntregaForm(initial={'fecha': sal.fecha}),
    })


@mat
@require_POST
def salida_insumo(request, pk):
    sal = get_object_or_404(ServicioMAT.objects.select_related('liquidacion'), pk=pk)
    form = EntregaForm(request.POST, instance=EntregaInsumo(liquidacion=sal.liquidacion, servicio=sal))
    if form.is_valid():
        e = form.save()
        messages.success(request, f'Agregado: {e.cantidad:g} × {e.articulo.nombre} ($ {e.total:,.2f}).'.replace(',', 'X').replace('.', ',').replace('X', '.'))
    else:
        messages.error(request, 'No se agregó: ' + ' '.join(e for es in form.errors.values() for e in es))
    return redirect('marcoantonio:salida', pk)


@mat
@require_POST
def salida_insumo_borrar(request, pk, entrega_pk):
    get_object_or_404(EntregaInsumo, pk=entrega_pk, servicio_id=pk).delete()
    messages.success(request, 'Insumo quitado de la salida.')
    return redirect('marcoantonio:salida', pk)


@mat
@require_POST
def entrega_asignar(request, pk, entrega_pk):
    """Pasa un insumo "del mes" a una salida (o lo devuelve al mes)."""
    entrega = get_object_or_404(EntregaInsumo, pk=entrega_pk, liquidacion_id=pk)
    salida_id = request.POST.get('servicio') or None
    entrega.servicio = get_object_or_404(ServicioMAT, pk=salida_id, liquidacion_id=pk) if salida_id else None
    entrega.save(update_fields=['servicio'])
    return redirect('marcoantonio:entregas', pk)


# ---------- Artículos ----------

@mat
def articulos(request, pk=None):
    articulo = get_object_or_404(Articulo, pk=pk) if pk else None
    form = ArticuloForm(request.POST or None, instance=articulo)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Artículo guardado. Las entregas ya cargadas mantienen su precio.')
        return redirect('marcoantonio:articulos')
    return render(request, 'marcoantonio/articulos.html', {'form': form, 'articulo': articulo,
                                                           'articulos': Articulo.objects.all()})


# ---------- Comprobantes y pagos ----------

def _guardar_con_imputaciones(request, objeto, form_clase, formset_clase, plantilla, titulo, destino, inicial=None):
    form = form_clase(request.POST or None, instance=objeto)
    formset = formset_clase(request.POST or None, instance=objeto, prefix='imp', initial=inicial)
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            guardado = form.save()
            formset.instance = guardado
            formset.save()
        messages.success(request, f'{titulo} guardado.')
        return redirect(destino)
    salidas_pendientes = [f for f in _filas_salidas(
        ServicioMAT.objects.select_related('liquidacion').prefetch_related(
            'insumos__articulo', 'liquidacion__servicios__insumos__articulo', 'liquidacion__imputaciones_pagos__pago'
        ).order_by('fecha')) if f['pagos']['saldo'] >= 1]
    return render(request, plantilla, {'form': form, 'formset': formset, 'titulo': titulo, 'objeto': objeto,
                                       'pendientes': _pendientes(), 'salidas_pendientes': salidas_pendientes})


def _pendientes():
    """Saldos por cobrar y por comprobar de cada liquidación, para ayudar a imputar."""
    filas = []
    for liq in Liquidacion.objects.prefetch_related('servicios', 'entregas__articulo'):
        for parte, nombre in PARTES:
            importe = liq.importe(parte)
            if importe:
                filas.append({'liq': liq, 'parte': nombre, 'importe': importe, 'saldo': liq.saldo(parte),
                              'sin_comprobante': liq.sin_comprobante(parte)})
    return filas


@mat
def comprobantes(request):
    lista = Comprobante.objects.prefetch_related('imputaciones__liquidacion', 'pagos')
    return render(request, 'marcoantonio/comprobantes.html', {'comprobantes': lista})


@mat
def comprobante_form(request, pk=None):
    objeto = get_object_or_404(Comprobante, pk=pk) if pk else Comprobante(fecha=timezone.localdate())
    return _guardar_con_imputaciones(request, objeto, ComprobanteForm, ImputacionesComprobanteFormSet,
                                     'marcoantonio/con_imputaciones.html', 'Comprobante', 'marcoantonio:comprobantes')


@mat
def pagos(request):
    lista = Pago.objects.select_related('comprobante').prefetch_related('imputaciones__liquidacion')
    return render(request, 'marcoantonio/pagos.html', {'pagos': lista})


@mat
def pago_form(request, pk=None):
    objeto = get_object_or_404(Pago, pk=pk) if pk else Pago(fecha=timezone.localdate())
    inicial = None
    if objeto.pk is None:
        objeto.creado_por = request.user
        sal = ServicioMAT.objects.filter(pk=request.GET.get('salida') or 0).first()
        if sal:
            # Viene desde una salida: el primer renglón ya apunta a esa salida
            inicial = [{'servicio': sal.pk, 'liquidacion': sal.liquidacion_id, 'parte': 'efectivo'}]
    return _guardar_con_imputaciones(request, objeto, PagoForm, ImputacionesPagoFormSet,
                                     'marcoantonio/con_imputaciones.html', 'Pago', 'marcoantonio:pagos', inicial)


@mat
@require_POST
def anular(request, tipo, pk):
    modelo = {'pago': Pago, 'comprobante': Comprobante}[tipo]
    objeto = get_object_or_404(modelo, pk=pk)
    objeto.anulado = not objeto.anulado
    objeto.save(update_fields=['anulado'])
    messages.success(request, f'{objeto} {"anulado: ya no cuenta en los saldos" if objeto.anulado else "vuelve a contar"}.')
    return redirect('marcoantonio:pagos' if tipo == 'pago' else 'marcoantonio:comprobantes')


# ---------- Importar y Excel ----------

@login_required
@user_passes_test(lambda u: u.is_superuser)
def importar(request):
    form = ImportarForm(request.POST or None, request.FILES or None)
    resultado = None
    if request.method == 'POST' and form.is_valid():
        try:
            resultado = importador.importar(form.cleaned_data['archivo'].read())
            messages.success(request, 'Planilla importada.')
        except importador.ErrorImportacion as e:
            messages.error(request, f'No se importó: {e}')
    return render(request, 'marcoantonio/importar.html', {'form': form, 'resultado': resultado})


@mat
def descargar_excel(request):
    respuesta = HttpResponse(excel.generar(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    respuesta['Content-Disposition'] = f'attachment; filename="Marco_Antonio_Tours_{timezone.localdate():%d-%m-%Y}.xlsx"'
    return respuesta


# ---------- Desde el cotizador ----------

@mat
@require_POST
def desde_cotizacion(request, cot_pk):
    from cotizador.models import Cotizacion
    from .desde_cotizacion import crear_salida, leer_tarifas
    cot = get_object_or_404(Cotizacion, pk=cot_pk, estado=Cotizacion.ACEPTADA)
    tarifas, error = leer_tarifas(request.POST)
    if error:
        messages.error(request, error)
        return redirect('cotizador:detalle', cot.pk)
    sal = crear_salida(cot, tarifas)
    messages.success(request, f'Listo: la cotización {cot.numero} ya es una salida de Marco Antonio '
                              f'({sal.liquidacion.nombre}). Cargale los insumos que lleve.')
    if sal.liquidacion.cerrada:
        messages.warning(request, f'Ojo: la liquidación de {sal.liquidacion.nombre} ya estaba cerrada.')
    return redirect('marcoantonio:salida', sal.pk)
