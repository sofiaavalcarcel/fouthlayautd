# Weekly Leads

Módulo para envíos generales de leads desde una matriz Excel. Usa las mismas
columnas y reglas de Weekly Forms: detecta el formulario indicado, procesa
cinco filas, espera 60 segundos, envía el formulario y verifica el lead en el
destino CRM elegido.

El motor de formularios se reutiliza mediante adaptadores para que las
correcciones de navegación, selección y verificación no se dupliquen.
También acepta URLs QA por textarea o Excel con país opcional, infiere el país,
valida el dominio, permite selección académica aleatoria y concilia en paralelo
InConcert y Balancer. Las filas con un Lead existente se omiten y el reporte
agrega enlaces individuales de ambos CRM. El modo opcional «Solo llenar, no
enviar» permite inspeccionar páginas sin hacer clic en el botón de envío, abrir
CRMs ni reservar teléfonos; QA.xlsx y reportes de landings con columnas
`pais`, `url`, `landing`, `carga_formularios_utel` y `Lead` se normalizan sin
repetir hojas espejo.
