"""Genera el Word de la cotización a partir de la plantilla (copia del modelo de Servinorte)."""
import io
import re
import zipfile
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape

from django.utils import timezone

PLANTILLA = Path(__file__).resolve().parent / 'plantilla' / 'cotizacion.docx'

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto',
         'septiembre', 'octubre', 'noviembre', 'diciembre']


def pesos(valor):
    """1700000 -> '1.700.000' (sin decimales, como en el modelo)."""
    return f'{round(valor):,.0f}'.replace(',', '.')


def porcentaje(valor):
    """10.50 -> '10,5'"""
    return f'{Decimal(valor).normalize():f}'.replace('.', ',')


def _repetir_parrafo(xml, marca, renglones):
    """El párrafo que tiene la marca se copia una vez por renglón (mantiene la viñeta)."""
    m = re.search(r'<w:p[ >](?:(?!<w:p[ >]).)*?' + re.escape(marca) + r'.*?</w:p>', xml, re.S)
    if not m:
        return xml
    parrafo = m.group(0)
    copias = ''.join(parrafo.replace(marca, escape(r)) for r in renglones) if renglones else ''
    return xml.replace(parrafo, copias, 1)


def generar(cot):
    salida = timezone.localtime(cot.salida)
    regreso = timezone.localtime(cot.regreso)
    neto = cot.tarifa_neta
    porc_iva = cot.porcentaje_iva
    bruto = cot.total_con_iva
    parametros = cot.detalle.get('parametros', {})

    texto_salida = salida.strftime('%d/%m/%Y %H:%M HS')
    if cot.texto_salida:
        texto_salida += ' ' + cot.texto_salida
    valores = {
        'FECHA': f'Salta, {cot.fecha.day} de {MESES[cot.fecha.month - 1]} {cot.fecha.year}',
        'NUMERO': str(cot.numero),
        'CLIENTE': cot.cliente.nombre.upper(),
        'SALIDA': texto_salida,
        'ITINERARIO': cot.itinerario,
        'REGRESO': regreso.strftime('%d/%m/%Y %H:%M HS.'),
        'CANTIDAD': f'{cot.cantidad_vehiculos:02d}',
        'VEHICULO': cot.descripcion_vehiculo,
        'NETO': pesos(neto),
        'IVA_PORC': porcentaje(porc_iva),
        'IVA': pesos(bruto - neto),
        'BRUTO': pesos(bruto),
        'VIGENCIA': parametros.get('Vigencia de la cotización (días)', '7'),
        'SENA': parametros.get('Seña (%)', '40'),
    }

    with zipfile.ZipFile(PLANTILLA) as z:
        archivos = {n: z.read(n) for n in z.namelist()}
    xml = archivos['word/document.xml'].decode('utf8')
    xml = _repetir_parrafo(xml, '{{INCLUYE}}', [r.strip() for r in cot.incluye.splitlines() if r.strip()])
    xml = _repetir_parrafo(xml, '{{NO_INCLUYE}}', [r.strip() for r in cot.no_incluye.splitlines() if r.strip()])
    for clave, valor in valores.items():
        xml = xml.replace('{{' + clave + '}}', escape(str(valor)))
    archivos['word/document.xml'] = xml.encode('utf8')

    salida_zip = io.BytesIO()
    with zipfile.ZipFile(salida_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in archivos.items():
            z.writestr(nombre, datos)
    return salida_zip.getvalue()


def nombre_archivo(cot):
    cliente = re.sub(r'[^A-Za-z0-9]+', '_', cot.cliente.nombre).strip('_') or 'cliente'
    return f'COT_{cot.numero}_{cliente}_{timezone.localtime(cot.salida):%d-%m-%y}.docx'
