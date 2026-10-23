"""Kilómetros por ruta usando los servicios gratuitos de OpenStreetMap.

- Nominatim: busca dónde queda cada lugar (se guarda en la tabla Lugar para no repetir).
- OSRM: calcula la distancia manejando por ruta entre los lugares, en orden.
"""
import requests
from django.conf import settings

from .models import Lugar

NOMINATIM = 'https://nominatim.openstreetmap.org/search'
OSRM = 'https://router.project-osrm.org/route/v1/driving/'
PAISES = 'ar,cl,bo,py,uy,br,pe'


class ErrorRuta(Exception):
    pass


def _headers():
    return {'User-Agent': settings.MAPAS_USER_AGENT, 'Accept-Language': 'es'}


def buscar_lugar(texto):
    clave = ' '.join(texto.split()).lower()
    lugar = Lugar.objects.filter(busqueda=clave).first()
    if lugar:
        return lugar
    intentos = [texto] if 'argentina' in clave else [f'{texto}, Argentina', texto]
    for consulta in intentos:
        try:
            r = requests.get(NOMINATIM, params={'q': consulta, 'format': 'json', 'limit': 1,
                                                'countrycodes': PAISES}, headers=_headers(), timeout=15)
            r.raise_for_status()
            resultados = r.json()
        except (requests.RequestException, ValueError) as e:
            raise ErrorRuta(f'No se pudo consultar el mapa ({e}). Probá de nuevo en un rato.')
        if resultados:
            res = resultados[0]
            return Lugar.objects.create(busqueda=clave, nombre=res['display_name'][:300],
                                        lat=float(res['lat']), lon=float(res['lon']))
    raise ErrorRuta(f'No encontré "{texto}" en el mapa. Probá escribiéndolo como "Ciudad, Provincia".')


def calcular_recorrido(origen, paradas, ida_y_vuelta=True):
    """Devuelve {'km': total, 'tramos': [{'desde','hasta','km'}], 'lugares': [...]}."""
    nombres = [origen] + [p for p in paradas if p.strip()]
    if len(nombres) < 2:
        raise ErrorRuta('Cargá al menos un destino.')
    if ida_y_vuelta:
        nombres.append(origen)
    lugares = [buscar_lugar(n) for n in nombres]
    coords = ';'.join(f'{l.lon},{l.lat}' for l in lugares)
    try:
        r = requests.get(OSRM + coords, params={'overview': 'false'}, headers=_headers(), timeout=20)
        datos = r.json()
    except (requests.RequestException, ValueError) as e:
        raise ErrorRuta(f'No se pudo calcular la ruta ({e}). Probá de nuevo en un rato.')
    if datos.get('code') != 'Ok' or not datos.get('routes'):
        raise ErrorRuta('El mapa no encontró un camino por ruta entre esos lugares.')
    tramos = []
    for i, tramo in enumerate(datos['routes'][0]['legs']):
        tramos.append({'desde': nombres[i], 'hasta': nombres[i + 1], 'km': round(tramo['distance'] / 1000)})
    return {'km': sum(t['km'] for t in tramos), 'tramos': tramos, 'lugares': lugares}
