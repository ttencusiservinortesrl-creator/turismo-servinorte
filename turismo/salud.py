from django.db import DatabaseError
from django.http import JsonResponse

from cotizador.models import Parametros


def salud(request):
    """Chequeo público, sin datos: lee la base para que Supabase (plan gratuito) no pause el proyecto por
    inactividad. Lo llama dos veces por día un workflow de GitHub (.github/workflows/mantener-activa.yml)."""
    try:
        Parametros.objects.exists()
    except DatabaseError:
        return JsonResponse({'ok': False}, status=503)
    return JsonResponse({'ok': True})
