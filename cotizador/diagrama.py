"""Lectura y escritura del "PL - DIAGRAMA DE VEHICULOS" (Excel compartido en Drive).

Formato de la planilla (una hoja por mes, "10-2026"):
- Una fila con las fechas del mes (fila 2; en algunas hojas, la 1), desde la columna B.
- En la columna A, el número interno de cada unidad ("61", "30 - TRANSIT"). Cada unidad usa hasta 3 renglones:
  cliente / recorrido / detalle. Un viaje de varios días se escribe combinando las celdas de esos días.

Para escribir NO se usa openpyxl para guardar (al guardar pierde comentarios y otras cosas del archivo):
se modifica directamente el XML de la hoja, solo en las celdas del viaje, y el resto queda igual.
"""
import io
import re
import warnings
import zipfile
from datetime import date, datetime, timedelta
from xml.sax.saxutils import escape

import openpyxl
from openpyxl.utils import column_index_from_string, get_column_letter

LIBRE = {'', 'LIBRE'}


class ErrorDiagrama(Exception):
    pass


def numero_unidad(valor):
    """'30 - TRANSIT' -> '30'; 61.0 -> '61'; 'HIACE' -> None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return str(int(valor))
    m = re.match(r'\s*(\d+)', str(valor))
    return m.group(1) if m else None


def nombre_hoja(dia):
    return f'{dia.month}-{dia.year}'


class Hoja:
    """Una hoja de mes ya interpretada."""

    def __init__(self, ws):
        self.ws = ws
        self.fila_fechas, self.columnas = self._fechas()
        self.unidades = self._unidades()
        # Para saber rápido si una celda está dentro de una combinación (y cuál es su celda principal).
        self.combinadas = {}
        for rango in ws.merged_cells.ranges:
            for fila in range(rango.min_row, rango.max_row + 1):
                for col in range(rango.min_col, rango.max_col + 1):
                    self.combinadas[(fila, col)] = (rango.min_row, rango.min_col)

    def _fechas(self):
        for fila in (1, 2, 3):
            columnas = {}
            for celda in self.ws[fila]:
                if isinstance(celda.value, datetime):
                    columnas[celda.value.date()] = celda.column
                elif isinstance(celda.value, date):
                    columnas[celda.value] = celda.column
            if len(columnas) >= 28:
                return fila, columnas
        raise ErrorDiagrama(f'No encontré las fechas en la hoja "{self.ws.title}".')

    def _unidades(self):
        """{'61': (fila_desde, fila_hasta)} con los renglones de cada unidad."""
        inicios = []
        for celda in self.ws['A']:
            if celda.row <= self.fila_fechas or celda.value in (None, ''):
                continue
            texto = str(celda.value).strip().upper()
            if texto.startswith('REFERENCIAS'):
                break
            inicios.append((celda.row, numero_unidad(celda.value)))
        unidades = {}
        for i, (fila, numero) in enumerate(inicios):
            siguiente = inicios[i + 1][0] if i + 1 < len(inicios) else fila + 3
            if numero:
                unidades[numero] = (fila, min(fila + 2, siguiente - 1))
        return unidades

    def texto(self, fila, col):
        principal = self.combinadas.get((fila, col), (fila, col))
        valor = self.ws.cell(*principal).value
        return '' if valor is None else str(valor).strip()

    def ocupacion(self, unidad, dia):
        """Texto de lo que tiene la unidad ese día ('' si está libre)."""
        filas = self.unidades.get(unidad)
        col = self.columnas.get(dia)
        if not filas or not col:
            return None
        textos = [self.texto(f, col) for f in range(filas[0], filas[1] + 1)]
        textos = [t for t in textos if t]
        if all(t.upper() in LIBRE for t in textos):
            return ''
        return ' / '.join(dict.fromkeys(textos))


class Diagrama:
    def __init__(self, contenido):
        self.contenido = contenido
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            self.libro = openpyxl.load_workbook(io.BytesIO(contenido))
        self._hojas = {}

    def hoja(self, dia):
        nombre = nombre_hoja(dia)
        if nombre not in self._hojas:
            if nombre not in self.libro.sheetnames:
                self._hojas[nombre] = None
            else:
                self._hojas[nombre] = Hoja(self.libro[nombre])
        return self._hojas[nombre]

    def disponibilidad(self, unidades, desde, hasta):
        """{'61': {fecha: '' (libre) | 'texto' (ocupada) | None (sin dato)}}."""
        dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
        resultado = {}
        for unidad in unidades:
            resultado[unidad] = {}
            for dia in dias:
                hoja = self.hoja(dia)
                resultado[unidad][dia] = hoja.ocupacion(unidad, dia) if hoja else None
        return resultado

    def libres(self, unidades, desde, hasta):
        disp = self.disponibilidad(unidades, desde, hasta)
        return [u for u in unidades if all(v == '' for v in disp[u].values())]


# ---------- Escritura ----------

def _hojas_xml(archivos):
    """{'10-2026': 'xl/worksheets/sheet10.xml'} leyendo workbook.xml y sus relaciones."""
    libro = archivos['xl/workbook.xml'].decode('utf8')
    rels = archivos['xl/_rels/workbook.xml.rels'].decode('utf8')
    destino = {}
    for m in re.finditer(r'<Relationship\b[^>]*>', rels):
        tag = m.group(0)
        rid = re.search(r'Id="([^"]+)"', tag).group(1)
        target = re.search(r'Target="([^"]+)"', tag).group(1)
        target = target.lstrip('/')
        destino[rid] = target if target.startswith('xl/') else 'xl/' + target
    hojas = {}
    for m in re.finditer(r'<sheet\b[^>]*/>', libro):
        tag = m.group(0)
        nombre = re.search(r'name="([^"]+)"', tag).group(1)
        rid = re.search(r'r:id="([^"]+)"', tag).group(1)
        hojas[nombre.replace('&amp;', '&')] = destino[rid]
    return hojas


def _celda_xml(ref, estilo, texto):
    s = f' s="{estilo}"' if estilo else ''
    if not texto:
        return f'<c r="{ref}"{s}/>'
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{escape(texto)}</t></is></c>'


def _poner_celda(xml, fila, col, texto):
    ref = f'{get_column_letter(col)}{fila}'
    m_fila = re.search(rf'<row\b[^>]*\br="{fila}"[^>]*?(?:/>|>(.*?)</row>)', xml, re.S)
    if not m_fila:
        # La fila no existe: se agrega en orden.
        nueva = f'<row r="{fila}">{_celda_xml(ref, None, texto)}</row>'
        siguiente = None
        for m in re.finditer(r'<row\b[^>]*\br="(\d+)"', xml):
            if int(m.group(1)) > fila:
                siguiente = m.start()
                break
        if siguiente is None:
            return xml.replace('</sheetData>', nueva + '</sheetData>', 1)
        return xml[:siguiente] + nueva + xml[siguiente:]
    fila_xml = m_fila.group(0)
    m_celda = re.search(rf'<c\b[^>]*\br="{ref}"[^>]*?(?:/>|>.*?</c>)', fila_xml, re.S)
    if m_celda:
        estilo = re.search(r'\bs="(\d+)"', m_celda.group(0))
        nueva_fila = fila_xml.replace(m_celda.group(0), _celda_xml(ref, estilo and estilo.group(1), texto), 1)
    else:
        nueva_celda = _celda_xml(ref, None, texto)
        if fila_xml.endswith('/>'):
            nueva_fila = fila_xml[:-2] + '>' + nueva_celda + '</row>'
        else:
            # Insertar en orden de columna
            posicion = None
            for m in re.finditer(r'<c\b[^>]*\br="([A-Z]+)\d+"', fila_xml):
                if column_index_from_string(m.group(1)) > col:
                    posicion = m.start()
                    break
            if posicion is None:
                posicion = fila_xml.rfind('</row>')
            nueva_fila = fila_xml[:posicion] + nueva_celda + fila_xml[posicion:]
    return xml.replace(fila_xml, nueva_fila, 1)


def _agregar_combinacion(xml, rango):
    m = re.search(r'<mergeCells\b[^>]*count="(\d+)"[^>]*>', xml)
    if m:
        nuevo = m.group(0).replace(f'count="{m.group(1)}"', f'count="{int(m.group(1)) + 1}"')
        xml = xml.replace(m.group(0), nuevo, 1)
        return xml.replace('</mergeCells>', f'<mergeCell ref="{rango}"/></mergeCells>', 1)
    return xml.replace('</sheetData>', f'</sheetData><mergeCells count="1"><mergeCell ref="{rango}"/></mergeCells>', 1)


def anotar(contenido, unidad, desde, hasta, renglones):
    """Escribe un viaje en el diagrama y devuelve el archivo nuevo (bytes).

    renglones: hasta 3 textos (cliente, recorrido, detalle). Si dura varios días, cada renglón se combina
    a lo largo de los días (como se hace a mano). Si el viaje cruza de mes, se escribe en las dos hojas.
    Falla (ErrorDiagrama) si la unidad no está libre en alguno de esos días."""
    diagrama = Diagrama(contenido)
    ocupados = {d: t for d, t in diagrama.disponibilidad([unidad], desde, hasta)[unidad].items() if t != ''}
    if ocupados:
        detalle = ', '.join(f'{d:%d/%m}: {t or "sin hoja en el diagrama"}' for d, t in ocupados.items())
        raise ErrorDiagrama(f'La unidad {unidad} no está libre ({detalle}).')

    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        archivos = {n: z.read(n) for n in z.namelist()}
        orden = z.namelist()
    rutas_hojas = _hojas_xml(archivos)

    # Agrupar los días por hoja (mes)
    por_hoja = {}
    dia = desde
    while dia <= hasta:
        por_hoja.setdefault(nombre_hoja(dia), []).append(dia)
        dia += timedelta(days=1)

    for nombre, dias in por_hoja.items():
        hoja = diagrama.hoja(dias[0])
        filas = hoja.unidades.get(unidad)
        if not filas:
            raise ErrorDiagrama(f'La unidad {unidad} no figura en la hoja "{nombre}".')
        col_desde, col_hasta = hoja.columnas[dias[0]], hoja.columnas[dias[-1]]
        ruta = rutas_hojas[nombre]
        xml = archivos[ruta].decode('utf8')
        for i, fila in enumerate(range(filas[0], filas[1] + 1)):
            texto = renglones[i] if i < len(renglones) else ''
            if not texto:
                continue
            xml = _poner_celda(xml, fila, col_desde, texto)
            if col_hasta > col_desde:
                xml = _agregar_combinacion(xml, f'{get_column_letter(col_desde)}{fila}:{get_column_letter(col_hasta)}{fila}')
        archivos[ruta] = xml.encode('utf8')

    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as z:
        for nombre in orden:
            z.writestr(nombre, archivos[nombre])
    return salida.getvalue()
