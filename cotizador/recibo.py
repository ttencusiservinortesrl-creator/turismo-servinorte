"""Recibo de pago en Word, con el mismo membrete (logo, márgenes, letra) que la cotización.

Toma la plantilla de la cotización y reemplaza el cuerpo del documento; el encabezado con el logo queda igual.
"""
import io
import re
import zipfile
from xml.sax.saxutils import escape

from django.utils import timezone

from .letras import pesos_en_letras
from .word import MESES, PLANTILLA, pesos

AZUL = '1F3B7A'


def _run(texto, negrita=False, tamano=None, color=None, subrayado=False):
    props = ''
    if negrita:
        props += '<w:b/><w:bCs/>'
    if subrayado:
        props += '<w:u w:val="single"/>'
    if color:
        props += f'<w:color w:val="{color}"/>'
    if tamano:
        props += f'<w:sz w:val="{tamano}"/><w:szCs w:val="{tamano}"/>'
    rpr = f'<w:rPr>{props}</w:rPr>' if props else ''
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


def _parrafo(*runs, alineacion=None, despues=120, antes=0):
    ppr = f'<w:spacing w:before="{antes}" w:after="{despues}"/>'
    if alineacion:
        ppr += f'<w:jc w:val="{alineacion}"/>'
    return f'<w:p><w:pPr>{ppr}</w:pPr>{"".join(runs)}</w:p>'


def _celda(contenido, ancho, fondo=None, alineacion=None, negrita=False, color=None):
    sombreado = f'<w:shd w:val="clear" w:color="auto" w:fill="{fondo}"/>' if fondo else ''
    borde = f'<w:tcBorders><w:top w:val="single" w:sz="6" w:color="{AZUL}"/><w:left w:val="single" w:sz="6" w:color="{AZUL}"/>' \
            f'<w:bottom w:val="single" w:sz="6" w:color="{AZUL}"/><w:right w:val="single" w:sz="6" w:color="{AZUL}"/></w:tcBorders>'
    return (f'<w:tc><w:tcPr><w:tcW w:w="{ancho}" w:type="dxa"/>{borde}{sombreado}'
            f'<w:tcMar><w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/><w:bottom w:w="80" w:type="dxa"/>'
            f'<w:right w:w="120" w:type="dxa"/></w:tcMar></w:tcPr>'
            f'{_parrafo(_run(contenido, negrita=negrita, color=color), alineacion=alineacion, despues=0)}</w:tc>')


def _tabla(filas, anchos):
    grilla = ''.join(f'<w:gridCol w:w="{a}"/>' for a in anchos)
    cuerpo = ''.join(f'<w:tr>{"".join(f)}</w:tr>' for f in filas)
    return f'<w:tbl><w:tblPr><w:tblW w:w="{sum(anchos)}" w:type="dxa"/><w:tblLayout w:type="fixed"/></w:tblPr>' \
           f'<w:tblGrid>{grilla}</w:tblGrid>{cuerpo}</w:tbl>'


def generar(mov):
    cot = mov.cotizacion
    cliente = cot.cliente
    fecha = mov.fecha
    salida = timezone.localtime(cot.salida)
    # Estado de cuenta: el total del servicio y lo pagado hasta este recibo inclusive.
    cargos = cot.total_cargos()
    pagado = sum(m.importe for m in cot.movimientos.filter(tipo='pago', numero_recibo__lte=mov.numero_recibo))

    datos_cliente = cliente.nombre.upper()
    if cliente.cuit:
        datos_cliente += f' – CUIT/DNI {cliente.cuit}'
    concepto = mov.concepto or 'Pago'
    detalle_viaje = f'{concepto} – COT {cot.numero}: {cot.itinerario} (salida {salida:%d/%m/%Y})'
    medio = mov.get_medio_display() + (f' – {mov.referencia}' if mov.referencia else '')

    cuerpo = [
        _parrafo(_run(f'Salta, {fecha.day} de {MESES[fecha.month - 1]} {fecha.year}'), alineacion='right', despues=200),
        _parrafo(_run(f'RECIBO N° {mov.numero_recibo:06d}', negrita=True, tamano=30, color=AZUL), alineacion='center', despues=60),
        _parrafo(_run('Documento no válido como factura', tamano=16, color='6B7487'), alineacion='center',
                 despues=120 if mov.anulado else 300),
        *([_parrafo(_run(f'*** ANULADO el {mov.anulado_en:%d/%m/%Y} — {mov.motivo_anulacion} ***' if mov.anulado_en
                         else '*** ANULADO ***', negrita=True, tamano=26, color='C00000'), alineacion='center', despues=300)]
          if mov.anulado else []),
        _parrafo(_run('Recibimos de '), _run(datos_cliente, negrita=True), _run(' la suma de '),
                 _run(pesos_en_letras(mov.importe), negrita=True), _run(f' ($ {pesos(mov.importe)}).'), despues=200),
        _tabla([
            [_celda('Concepto', 6600, fondo=AZUL, negrita=True, color='FFFFFF'),
             _celda('Importe', 3000, fondo=AZUL, negrita=True, color='FFFFFF', alineacion='right')],
            [_celda(detalle_viaje, 6600), _celda(f'$ {pesos(mov.importe)}', 3000, alineacion='right', negrita=True)],
            [_celda(f'Forma de pago: {medio}', 6600), _celda('', 3000)],
        ], [6600, 3000]),
        _parrafo(_run('ESTADO DE CUENTA DEL SERVICIO', negrita=True, subrayado=True), antes=300, despues=80),
        _tabla([
            [_celda('Total del servicio (con IVA)', 6600), _celda(f'$ {pesos(cargos)}', 3000, alineacion='right')],
            [_celda('Pagado a la fecha (incluye este recibo)', 6600), _celda(f'$ {pesos(pagado)}', 3000, alineacion='right')],
            [_celda('Saldo pendiente', 6600, fondo='E6EDFA', negrita=True),
             _celda(f'$ {pesos(cargos - pagado)}', 3000, fondo='E6EDFA', alineacion='right', negrita=True)],
        ], [6600, 3000]),
        _parrafo(_run(''), despues=900),
        _parrafo(_run('……………………………………………'), alineacion='right', despues=0),
        _parrafo(_run('Firma y aclaración'), alineacion='right', despues=400),
        _parrafo(_run('SERVINORTE', negrita=True), alineacion='right', despues=0),
        _parrafo(_run('Independencia 726, Salta - ARG'), alineacion='right', despues=0),
    ]

    with zipfile.ZipFile(PLANTILLA) as z:
        archivos = {n: z.read(n) for n in z.namelist()}
    xml = archivos['word/document.xml'].decode('utf8')
    seccion = re.search(r'<w:sectPr.*?</w:sectPr>', xml, re.S).group(0)
    xml = re.sub(r'<w:body>.*</w:body>', lambda m: f'<w:body>{"".join(cuerpo)}{seccion}</w:body>', xml, flags=re.S)
    archivos['word/document.xml'] = xml.encode('utf8')

    salida_zip = io.BytesIO()
    with zipfile.ZipFile(salida_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for nombre, contenido in archivos.items():
            z.writestr(nombre, contenido)
    return salida_zip.getvalue()


def nombre_archivo(mov):
    cliente = re.sub(r'[^A-Za-z0-9]+', '_', mov.cotizacion.cliente.nombre).strip('_') or 'cliente'
    return f'Recibo_{mov.numero_recibo:06d}_{cliente}.docx'
