# API HTTP

`routes.py` contiene el contrato REST de la aplicación. Cada bloque de rutas está agrupado por capacidad: salud y dashboard, IA, bot genérico, bot UTEL/InConcert, ejecución por lote, Weekly Auto, PDP y grabador de acciones.

Las rutas no deben contener consultas SQL ni selectores de navegador; validan la petición, crean o consultan el trabajo asíncrono y delegan la operación al servicio correspondiente.
