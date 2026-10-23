"""Convierte un Word de cotización real en la plantilla que usa la app.

Uso: venv\\Scripts\\python scripts\\preparar_plantilla.py COT_ejemplo.docx

Reemplaza los datos variables (fecha, número, cliente, salida, itinerario, regreso,
vehículo, importes, ítems de incluye/no incluye, seña y vigencia) por marcas {{...}}
y deja el resto (logo, formato, condiciones) igual. Sirve para el modelo de Word
de Servinorte; si cambia mucho el modelo, hay que revisar los índices de abajo.
"""
import re
import sys
import zipfile
from pathlib import Path

DESTINO = Path(__file__).resolve().parent.parent / 'cotizador' / 'plantilla' / 'cotizacion.docx'

PARRAFO = re.compile(r'<w:p[ >].*?</w:p>', re.S)
RUN = re.compile(r'<w:r[ >].*?</w:r>', re.S)


def poner_textos(parrafo, textos):
    """Asigna un texto a cada run del párrafo (por posición) y borra los runs sobrantes."""
    runs = RUN.findall(parrafo)
    nuevo = parrafo
    for i, run in enumerate(runs):
        if i < len(textos):
            reemplazo = re.sub(r'<w:t[^>]*>[^<]*</w:t>',
                               f'<w:t xml:space="preserve">{textos[i]}</w:t>', run, count=1)
        else:
            reemplazo = ''
        nuevo = nuevo.replace(run, reemplazo, 1)
    return nuevo


def main(origen):
    with zipfile.ZipFile(origen) as z:
        archivos = {n: z.read(n) for n in z.namelist()}
    xml = archivos['word/document.xml'].decode('utf8')
    parrafos = PARRAFO.findall(xml)

    cambios = {
        0: ['{{FECHA}}'],
        1: ['COT', ' {{NUMERO}}', ' – {{CLIENTE}}'],
        3: ['SALIDA: ', '{{SALIDA}}'],
        4: ['ITINERARIO: ', '{{ITINERARIO}}'],
        5: ['REGRESO: ', '{{REGRESO}}'],
        6: ['{{CANTIDAD}} ', '{{VEHICULO}}'],
        7: ['TOTAL: ${{NETO}}'],
        8: ['+IVA {{IVA_PORC}}%: ${{IVA}}'],
        9: ['TOTAL: ${{BRUTO}}'],
        11: ['{{INCLUYE}}'],
        12: [], 13: [], 14: [],
        16: ['{{NO_INCLUYE}}'],
        20: ['Esta tarifa tiene vigencia de {{VIGENCIA}} días de corrido, pasado este periodo, '
             'la misma puede llegar a sufrir modificaciones.'],
        26: ['De confirmarse la realización del viaje, deberán abonar seña del {{SENA}}% ',
             'según vehículo y servicio elegido. En caso de cancelación, la misma no tiene reintegro.'],
    }
    for indice, textos in cambios.items():
        viejo = parrafos[indice]
        nuevo = '' if not textos else poner_textos(viejo, textos)
        xml = xml.replace(viejo, nuevo, 1)

    archivos['word/document.xml'] = xml.encode('utf8')
    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(DESTINO, 'w', zipfile.ZIP_DEFLATED) as z:
        for nombre, datos in archivos.items():
            z.writestr(nombre, datos)
    print('Plantilla guardada en', DESTINO)


if __name__ == '__main__':
    main(sys.argv[1])
