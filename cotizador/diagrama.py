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
TAN = 'TAN'  # salidas del Tren a las Nubes: la unidad sigue disponible para turismo, pero se avisa


class ErrorDiagrama(Exception):
    pass


def _partes(texto):
    return [t.strip().upper() for t in (texto or '').split(' / ') if t.strip()]


def es_tan(texto):
    """True si ese día la unidad solo tiene "TAN" (y quizás "LIBRE")."""
    partes = _partes(texto)
    return TAN in partes and all(t in (TAN, 'LIBRE') for t in partes)


def disponible(texto):
    """Libre o solo con salida de TAN (se puede usar, avisando)."""
    return texto == '' or es_tan(texto)


def estado(texto):
    if texto is None:
        return 'sin_dato'
    if texto == '':
        return 'libre'
    return 'tan' if es_tan(texto) else 'ocupada'


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

    def color(self, unidad, dia):
        """Color de fondo de lo que tiene la unidad ese día, como en la planilla ('#E68EE6'), o None."""
        filas = self.unidades.get(unidad)
        col = self.columnas.get(dia)
        if not filas or not col:
            return None
        for fila in range(filas[0], filas[1] + 1):
            principal = self.combinadas.get((fila, col), (fila, col))
            celda = self.ws.cell(*principal)
            if celda.value in (None, ''):
                continue
            relleno = celda.fill
            if relleno is not None and relleno.fill_type == 'solid' and relleno.fgColor is not None \
                    and relleno.fgColor.type == 'rgb' and isinstance(relleno.fgColor.rgb, str):
                rgb = relleno.fgColor.rgb[-6:].upper()
                if rgb not in ('FFFFFF', '000000'):
                    return '#' + rgb
        return None

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

    def colores(self, unidades, desde, hasta):
        dias = [desde + timedelta(days=i) for i in range((hasta - desde).days + 1)]
        return {u: {d: (self.hoja(d).color(u, d) if self.hoja(d) else None) for d in dias} for u in unidades}

    def libres(self, unidades, desde, hasta):
        """Unidades disponibles todos esos días (libres o solo con TAN)."""
        disp = self.disponibilidad(unidades, desde, hasta)
        return [u for u in unidades if all(v is not None and disponible(v) for v in disp[u].values())]


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


def _poner_celda(xml, fila, col, texto, estilo=None):
    """Pone el texto en la celda ('' la deja vacía). `estilo` reemplaza el formato que tenía (si se indica)."""
    ref = f'{get_column_letter(col)}{fila}'
    m_fila = re.search(rf'<row\b[^>]*\br="{fila}"[^>]*?(?:/>|>(.*?)</row>)', xml, re.S)
    if not m_fila:
        # La fila no existe: se agrega en orden.
        nueva = f'<row r="{fila}">{_celda_xml(ref, estilo, texto)}</row>'
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
        if estilo is None:
            actual = re.search(r'\bs="(\d+)"', m_celda.group(0))
            estilo = actual and actual.group(1)
        nueva_fila = fila_xml.replace(m_celda.group(0), _celda_xml(ref, estilo, texto), 1)
    else:
        nueva_celda = _celda_xml(ref, estilo, texto)
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


def _estilo_blanco(xml, fila):
    """Estilo de las celdas vacías de esa fila (el más usado), para que la reserva no quede con el color del TAN."""
    m_fila = re.search(rf'<row\b[^>]*\br="{fila}"[^>]*?(?:/>|>(.*?)</row>)', xml, re.S)
    if not m_fila or not m_fila.group(1):
        return None
    estilos = re.findall(r'<c\b[^>]*?\bs="(\d+)"[^>]*?/>', m_fila.group(1))
    return max(set(estilos), key=estilos.count) if estilos else None


def _quitar_combinacion(xml, rango):
    tag = f'<mergeCell ref="{rango}"/>'
    if tag not in xml:
        return xml
    xml = xml.replace(tag, '', 1)
    m = re.search(r'<mergeCells\b[^>]*count="(\d+)"[^>]*>', xml)
    if m:
        xml = xml.replace(m.group(0), m.group(0).replace(f'count="{m.group(1)}"', f'count="{int(m.group(1)) - 1}"'), 1)
    return xml


def anotar(contenido, unidad, desde, hasta, renglones):
    """Escribe un viaje en el diagrama y devuelve el archivo nuevo (bytes).

    renglones: hasta 3 textos (cliente, recorrido, detalle). Si dura varios días, cada renglón se combina
    a lo largo de los días (como se hace a mano). Si el viaje cruza de mes, se escribe en las dos hojas.
    Los días que solo tenían salida de TAN se liberan: se borra el TAN y queda la reserva.
    Falla (ErrorDiagrama) si la unidad está ocupada con otra cosa en alguno de esos días."""
    diagrama = Diagrama(contenido)
    por_dia = diagrama.disponibilidad([unidad], desde, hasta)[unidad]
    ocupados = {d: t for d, t in por_dia.items() if t is None or not disponible(t)}
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

        # 1) Sacar el TAN (o "LIBRE") de esos días: celdas y combinaciones que haya dentro del bloque.
        for rango in list(hoja.ws.merged_cells.ranges):
            if rango.max_row < filas[0] or rango.min_row > filas[1] or rango.max_col < col_desde or rango.min_col > col_hasta:
                continue
            if rango.min_col < col_desde or rango.max_col > col_hasta or rango.min_row < filas[0] or rango.max_row > filas[1]:
                raise ErrorDiagrama(f'La unidad {unidad} tiene una celda combinada que sigue fuera de las fechas del viaje '
                                    f'({rango.coord}). Corregila a mano en el Excel.')
            xml = _quitar_combinacion(xml, rango.coord)
        estilos_blancos = {}
        for fila in range(filas[0], filas[1] + 1):
            estilos_blancos[fila] = _estilo_blanco(xml, fila)
            for col in range(col_desde, col_hasta + 1):
                valor = hoja.ws.cell(fila, col).value
                if valor not in (None, ''):
                    xml = _poner_celda(xml, fila, col, '', estilo=estilos_blancos[fila])

        # 2) Escribir la reserva combinando las celdas de los días del viaje.
        for i, fila in enumerate(range(filas[0], filas[1] + 1)):
            texto = renglones[i] if i < len(renglones) else ''
            if not texto:
                continue
            tenia_algo = hoja.ws.cell(fila, col_desde).value not in (None, '')
            xml = _poner_celda(xml, fila, col_desde, texto, estilo=estilos_blancos[fila] if tenia_algo else None)
            if col_hasta > col_desde:
                xml = _agregar_combinacion(xml, f'{get_column_letter(col_desde)}{fila}:{get_column_letter(col_hasta)}{fila}')
        archivos[ruta] = xml.encode('utf8')

    salida = io.BytesIO()
    with zipfile.ZipFile(salida, 'w', zipfile.ZIP_DEFLATED) as z:
        for nombre in orden:
            z.writestr(nombre, archivos[nombre])
    return salida.getvalue()
