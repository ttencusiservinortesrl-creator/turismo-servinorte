from .models import RUBROS


def rubros(request):
    """Los rubros de Marco Antonio, para las pestañas de todas sus pantallas."""
    return {'rubros_mat': RUBROS}
