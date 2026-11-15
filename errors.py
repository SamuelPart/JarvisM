"""Safe, actionable error messages without exposing provider responses or keys."""
from google.genai import errors as genai_errors
from nvidia_brain import NvidiaError


def describe_error(exc):
    if isinstance(exc, NvidiaError):
        code = exc.status
        if code in (401, 403):
            return f'NVIDIA rechazó la clave o los permisos (HTTP {code}); revisa la configuración local sin compartirla.'
        if code == 429:
            return 'NVIDIA alcanzó un límite de uso o cuota (HTTP 429). Espera y revisa tu cuenta.'
        if code in (400, 404, 422):
            return f'NVIDIA rechazó la solicitud o el modelo (HTTP {code}); revisa disponibilidad y soporte de herramientas.'
        if isinstance(code, int):
            return f'NVIDIA devolvió un error HTTP {code}; vuelve a intentarlo.'
        return 'No se pudo conectar con NVIDIA o su respuesta no fue válida.'
    if isinstance(exc, genai_errors.APIError):
        code = getattr(exc, 'code', None)
        if code in (400, 422):
            return f'Gemini rechazó la solicitud (HTTP {code}). Comprueba que el modelo admita herramientas y vuelve a intentarlo.'
        if code in (401, 403):
            return f'Gemini rechazó la autorización (HTTP {code}). Revisa localmente la clave y los permisos de la API; no compartas la clave.'
        if code == 404:
            return 'Gemini no encontró el modelo (HTTP 404). Revisa GEMINI_MODEL y el acceso de tu cuenta.'
        if code == 429:
            return 'Gemini alcanzó un límite de uso o cuota (HTTP 429). Espera y revisa la cuota de tu cuenta.'
        if isinstance(code, int) and 500 <= code < 600:
            return f'El servicio Gemini falló temporalmente (HTTP {code}). Inténtalo más tarde.'
        if isinstance(code, int):
            return f'La API de Gemini devolvió un error HTTP {code}. Vuelve a intentarlo.'
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return 'No se pudo conectar con Gemini o se agotó el tiempo de espera. Revisa tu conexión.'
    return f'No se pudo completar la solicitud ({type(exc).__name__}).'
