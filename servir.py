r"""Levanta el cotizador en esta PC con el servidor de producción (waitress).
Uso: venv\Scripts\python servir.py   y abrir http://127.0.0.1:8050"""
import os
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'turismo.settings')

from waitress import serve  # noqa: E402

from turismo.wsgi import application  # noqa: E402

if __name__ == '__main__':
    puerto = os.environ.get('PORT') or os.environ.get('PUERTO', '8050')
    print(f'Cotizador funcionando en http://127.0.0.1:{puerto}')
    serve(application, listen=f'127.0.0.1:{puerto}')
