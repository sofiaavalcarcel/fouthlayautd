# Weekly Performance

Procesa un `.xlsx` mediante PageSpeed Insights:

- lee URLs HTTP/HTTPS desde la columna D, a partir de la fila 2;
- escribe el puntaje Desktop en la columna L y Móvil en la columna M;
- permite elegir la pestaña (por defecto `Hoja 1`) y entre 1 y 16 procesos simultáneos;
- reintenta errores temporales y límites HTTP 429 con espera progresiva;
- guarda un checkpoint cada 10 resultados y conserva un Excel parcial al detenerse.

La clave se configura de forma segura con `PAGESPEED_API_KEY` en `.env`. También puede funcionar sin clave, sujeto a la cuota pública de Google.
