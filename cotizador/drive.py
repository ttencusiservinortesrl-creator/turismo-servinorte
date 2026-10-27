"""Conexión con Google Drive para leer y escribir el diagrama de unidades.

La app usa una "cuenta de servicio" de Google (un usuario técnico). Su clave va en la variable de entorno
GOOGLE_SERVICE_ACCOUNT_JSON (el contenido completo del archivo .json) y el diagrama tiene que estar
compartido con el mail de esa cuenta como Editor. Ver docs/conectar-diagrama.md.

Para probar en una PC sin tocar el archivo real: DIAGRAMA_LOCAL=<ruta de una copia del Excel> (lee y escribe esa copia).
"""
import json
import os
import time

from . import diagrama as dg

API = 'https://www.googleapis.com/drive/v3/files/'
SUBIDA = 'https://www.googleapis.com/upload/drive/v3/files/'
XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
CACHE_SEGUNDOS = 120

_cache = {}  # file_id -> (momento, contenido, modifiedTime)


class ErrorDrive(Exception):
    pass


def _local():
    return os.environ.get('DIAGRAMA_LOCAL', '')


def configurado():
    return bool(_local() or os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON'))


def mail_cuenta():
    try:
        return json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']).get('client_email')
    except (KeyError, ValueError):
        return None


def _sesion():
    if not configurado():
        raise ErrorDrive('Falta conectar la app con Drive (ver "Conectar el diagrama" en Unidades).')
    from google.auth.transport.requests import AuthorizedSession
    from google.oauth2 import service_account
    try:
        info = json.loads(os.environ['GOOGLE_SERVICE_ACCOUNT_JSON'])
        credenciales = service_account.Credentials.from_service_account_info(
            info, scopes=['https://www.googleapis.com/auth/drive'])
    except (ValueError, KeyError) as e:
        raise ErrorDrive(f'La clave de Google cargada en el servidor no es válida ({e}).')
    return AuthorizedSession(credenciales)


def _revisar(respuesta, accion):
    if respuesta.status_code == 404:
        raise ErrorDrive(f'No encuentro el diagrama en Drive. Revisá que esté compartido con {mail_cuenta()} '
                         f'y que el código en Parámetros sea el correcto.')
    if respuesta.status_code == 403:
        raise ErrorDrive(f'Drive no deja {accion} el diagrama: compartilo con {mail_cuenta()} como Editor.')
    if respuesta.status_code >= 400:
        raise ErrorDrive(f'Drive respondió con un error al {accion} el diagrama (código {respuesta.status_code}).')


def _datos(file_id, sesion):
    r = sesion.get(API + file_id, params={'fields': 'name,modifiedTime', 'supportsAllDrives': 'true'}, timeout=30)
    _revisar(r, 'leer')
    return r.json()


def descargar(file_id, usar_cache=True):
    """Devuelve (contenido, modifiedTime). Guarda una copia 2 minutos para no bajarlo en cada pantalla."""
    if _local():
        with open(_local(), 'rb') as f:
            return f.read(), str(os.path.getmtime(_local()))
    ahora = time.monotonic()
    if usar_cache and file_id in _cache and ahora - _cache[file_id][0] < CACHE_SEGUNDOS:
        return _cache[file_id][1], _cache[file_id][2]
    sesion = _sesion()
    datos = _datos(file_id, sesion)
    r = sesion.get(API + file_id, params={'alt': 'media', 'supportsAllDrives': 'true'}, timeout=60)
    _revisar(r, 'leer')
    _cache[file_id] = (ahora, r.content, datos['modifiedTime'])
    return r.content, datos['modifiedTime']


def anotar(file_id, viajes):
    """viajes: lista de (unidad, desde, hasta, renglones)."""
    def cambio(contenido):
        for unidad, desde, hasta, renglones in viajes:
            contenido = dg.anotar(contenido, unidad, desde, hasta, renglones)
        return contenido
    modificar(file_id, cambio)


def quitar(file_id, reservas):
    """reservas: lista de (unidad, desde, hasta, cliente) a borrar del diagrama."""
    def cambio(contenido):
        for unidad, desde, hasta, cliente in reservas:
            contenido = dg.quitar(contenido, unidad, desde, hasta, cliente)
        return contenido
    modificar(file_id, cambio)


def modificar(file_id, cambio):
    """Baja la última versión, le aplica `cambio` y la sube. Si alguien modificó el archivo mientras tanto,
    no sube nada y avisa."""
    contenido, version = descargar(file_id, usar_cache=False)
    contenido = cambio(contenido)
    if _local():
        with open(_local(), 'wb') as f:
            f.write(contenido)
        return
    sesion = _sesion()
    if _datos(file_id, sesion)['modifiedTime'] != version:
        raise ErrorDrive('Alguien modificó el diagrama recién. Probá de nuevo para que lea la versión nueva.')
    r = sesion.patch(SUBIDA + file_id, params={'uploadType': 'media', 'supportsAllDrives': 'true'},
                     data=contenido, headers={'Content-Type': XLSX}, timeout=60)
    _revisar(r, 'escribir')
    _cache.pop(file_id, None)


def diagrama_actual(parametros):
    """El diagrama interpretado (o ErrorDrive / ErrorDiagrama)."""
    if not parametros.diagrama_drive_id:
        raise ErrorDrive('Falta el código del diagrama en Parámetros.')
    contenido, _ = descargar(parametros.diagrama_drive_id)
    return dg.Diagrama(contenido)
