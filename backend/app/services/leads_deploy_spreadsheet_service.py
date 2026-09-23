"""Compatibilidad temporal para Bot Leads Deploy.

La implementación real vive en:
backend/app/modules/bot_leads_deploy/

Este puente existe mientras terminamos de mover todos los imports del backend a
la nueva estructura de módulos. No agregues lógica nueva en este archivo.
"""

from ..modules.bot_leads_deploy.service import LeadsDeploySpreadsheetService

__all__ = ["LeadsDeploySpreadsheetService"]
