# Servicios del frontend

Esta capa centraliza la comunicación con FastAPI. `api.js` resuelve la URL correcta para web o Electron, normaliza errores HTTP y expone funciones con nombres de negocio. No debe incluir lógica de presentación ni manipulación del DOM.
