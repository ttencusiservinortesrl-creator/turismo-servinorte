from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from . import control, excel, importador
from .forms import (ArticuloForm, ComprobanteForm, EntregaForm, ImportarForm, ImputacionesComprobanteFormSet,
                    ImputacionesPagoFormSet, LiquidacionForm, PagoForm, ServicioForm)
from .models import PARTES, Articulo, Comprobante, EntregaInsumo, Liquidacion, Pago, ServicioMAT


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
        'imputaciones_pagos': liq.imputaciones_pagos.select_related('pago').order_by('pago__fecha'),
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
    return render(request, 'marcoantonio/entregas.html', {'liq': liq, 'entregas': liq.entregas.select_related('articulo')})


@mat
@require_POST
def entrega_borrar(request, pk, entrega_pk):
    get_object_or_404(EntregaInsumo, pk=entrega_pk, liquidacion_id=pk).delete()
    messages.success(request, 'Entrega borrada.')
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

def _guardar_con_imputaciones(request, objeto, form_clase, formset_clase, plantilla, titulo, destino):
    form = form_clase(request.POST or None, instance=objeto)
    formset = formset_clase(request.POST or None, instance=objeto, prefix='imp')
    if request.method == 'POST' and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            guardado = form.save()
            formset.instance = guardado
            formset.save()
        messages.success(request, f'{titulo} guardado.')
        return redirect(destino)
    return render(request, plantilla, {'form': form, 'formset': formset, 'titulo': titulo, 'objeto': objeto,
                                       'pendientes': _pendientes()})


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
    if objeto.pk is None:
        objeto.creado_por = request.user
    return _guardar_con_imputaciones(request, objeto, PagoForm, ImputacionesPagoFormSet,
                                     'marcoantonio/con_imputaciones.html', 'Pago', 'marcoantonio:pagos')


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
