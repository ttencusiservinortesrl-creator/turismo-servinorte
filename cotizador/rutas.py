"""Kilómetros por ruta usando servicios gratuitos basados en OpenStreetMap.

- Buscar dónde queda cada lugar: Nominatim y, si no responde o rechaza el pedido, Photon.
  Lo encontrado se guarda en la tabla Lugar para no volver a buscarlo.
- Distancia manejando entre los lugares, en orden: OSRM y, si falla, el OSRM de openstreetmap.de.

Los servicios gratuitos a veces rechazan pedidos que salen de servidores en la nube (como Render);
por eso hay un respaldo para cada paso y el error dice qué servicio falló.
"""
import logging

import requests
from django.conf import settings

from .models import Lugar

logger = logging.getLogger(__name__)

NOMINATIM = 'https://nominatim.openstreetmap.org/search'
PHOTON = 'https://photon.komoot.io/api/'
RUTEADORES = [
    ('OSRM', 'https://router.project-osrm.org/route/v1/driving/'),
    ('OSRM Alemania', 'https://routing.openstreetmap.de/routed-car/route/v1/driving/'),
]
PAISES = 'ar,cl,bo,py,uy,br,pe'
SUDAMERICA = '-82,-56,-34,13'  # recuadro para que Photon no devuelva lugares de otros continentes


class ErrorRuta(Exception):
    pass


class _ServicioCaido(Exception):
    """El servicio no respondió bien (rechazo, error o demora); se prueba el siguiente."""


def _headers():
    return {'User-Agent': settings.MAPAS_USER_AGENT, 'Accept-Language': 'es'}


def _pedir(nombre, url, params=None, timeout=15):
    try:
        r = requests.get(url, params=params, headers=_headers(), timeout=timeout)
    except requests.RequestException as e:
        logger.warning('Mapa: %s no respondió: %s', nombre, e)
        raise _ServicioCaido(f'{nombre} no respondió')
    if r.status_code != 200:
        logger.warning('Mapa: %s devolvió %s: %s', nombre, r.status_code, r.text[:200])
        raise _ServicioCaido(f'{nombre} rechazó el pedido (código {r.status_code})')
    try:
        return r.json()
    except ValueError:
        logger.warning('Mapa: %s devolvió algo que no es JSON: %s', nombre, r.text[:200])
        raise _ServicioCaido(f'{nombre} devolvió una respuesta inválida')


def _nominatim(consulta):
    resultados = _pedir('Nominatim', NOMINATIM, {'q': consulta, 'format': 'json', 'limit': 1, 'countrycodes': PAISES})
    if resultados:
        res = resultados[0]
        return res['display_name'], float(res['lat']), float(res['lon'])
    return None


def _photon(consulta):
    datos = _pedir('Photon', PHOTON, {'q': consulta, 'limit': 1, 'bbox': SUDAMERICA})
    for f in datos.get('features', []):
        p = f.get('properties', {})
        partes = [p.get('name'), p.get('city') or p.get('county'), p.get('state'), p.get('country')]
        nombre = ', '.join(dict.fromkeys(x for x in partes if x))
        lon, lat = f['geometry']['coordinates']
        return nombre, float(lat), float(lon)
    return None


def buscar_lugar(texto):
    clave = ' '.join(texto.split()).lower()
    lugar = Lugar.objects.filter(busqueda=clave).first()
    if lugar:
        return lugar
    intentos = [texto] if 'argentina' in clave else [f'{texto}, Argentina', texto]
    fallas = []
    for buscador in (_nominatim, _photon):
        try:
            for consulta in intentos:
                encontrado = buscador(consulta)
                if encontrado:
                    nombre, lat, lon = encontrado
                    return Lugar.objects.create(busqueda=clave, nombre=nombre[:300], lat=lat, lon=lon)
            # Respondió pero no lo encontró: el otro buscador puede tenerlo con otro nombre.
        except _ServicioCaido as e:
            fallas.append(str(e))
    if len(fallas) == 2:
        raise ErrorRuta(f'No se pudo consultar el mapa ({"; ".join(fallas)}). Probá de nuevo en un rato '
                        f'o cargá los km a mano.')
    raise ErrorRuta(f'No encontré "{texto}" en el mapa. Probá escribiéndolo como "Ciudad, Provincia".')


def estado_servicios():
    """Prueba cada servicio con un lugar fijo (Salta → Metán). Solo dice si responde; no usa datos de clientes."""
    pruebas = {
        'Nominatim': lambda: _nominatim('Metán, Salta, Argentina'),
        'Photon': lambda: _photon('Metán, Salta'),
    }
    for nombre, url in RUTEADORES:
        pruebas[nombre] = lambda url=url, nombre=nombre: _pedir(nombre, url + '-65.41,-24.79;-64.97,-25.49', {'overview': 'false'})
    estado = {}
    for nombre, prueba in pruebas.items():
        try:
            estado[nombre] = 'responde' if prueba() else 'responde pero no encontró el lugar'
        except _ServicioCaido as e:
            estado[nombre] = str(e)
    return estado


def calcular_recorrido(origen, paradas, ida_y_vuelta=True):
    """Devuelve {'km': total, 'tramos': [{'desde','hasta','km'}], 'lugares': [...]}."""
    nombres = [origen] + [p for p in paradas if p.strip()]
    if len(nombres) < 2:
        raise ErrorRuta('Cargá al menos un destino.')
    if ida_y_vuelta:
        nombres.append(origen)
    lugares = [buscar_lugar(n) for n in nombres]
    coords = ';'.join(f'{l.lon},{l.lat}' for l in lugares)
    fallas = []
    for nombre, url in RUTEADORES:
        try:
            datos = _pedir(nombre, url + coords, {'overview': 'false'}, timeout=20)
        except _ServicioCaido as e:
            fallas.append(str(e))
            continue
        if datos.get('code') == 'Ok' and datos.get('routes'):
            tramos = [{'desde': nombres[i], 'hasta': nombres[i + 1], 'km': round(t['distance'] / 1000)}
                      for i, t in enumerate(datos['routes'][0]['legs'])]
            return {'km': sum(t['km'] for t in tramos), 'tramos': tramos, 'lugares': lugares}
        raise ErrorRuta('El mapa no encontró un camino por ruta entre esos lugares.')
    raise ErrorRuta(f'No se pudo calcular la ruta ({"; ".join(fallas)}). Probá de nuevo en un rato o cargá los km a mano.')
