"""Runner exclusivo de Bot Leads Deploy.

Al inicio hereda el comportamiento estable del Bot de nuevos productos.
Los cambios futuros de Leads Deploy deben hacerse sobrescribiendo métodos aquí,
sin editar backend/app/automations/utel_inconcert/runner.py.
"""

from ..utel_inconcert.runner import UtelInconcertRunner


class LeadsDeployRunner(UtelInconcertRunner):
    """Punto de extensión aislado para el flujo Leads Deploy."""

    pass
