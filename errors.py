"""Safe, actionable error messages without exposing provider responses or keys."""
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
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return 'No se pudo conectar con NVIDIA o se agotó el tiempo de espera. Revisa tu conexión.'
    return f'No se pudo completar la solicitud ({type(exc).__name__}).'
