# Interfaz de Bot de nuevos productos

Tema basado en la referencia visual facilitada para este módulo: configuración
arriba a la izquierda, diagnóstico debajo y resultados en la columna derecha.

## Archivos

- `visual.css`: distribución, colores, iconos SVG locales, botones y responsive.
- `visual.js`: carga del tema, fecha reflejada desde `#today-label`, textos de
  presentación y reubicación del mismo botón de guía en Opciones avanzadas.
- `../../renderer/gooey-buttons.js`: arranque visual; importa este componente de
  forma independiente. Si no carga, las automatizaciones siguen arrancando.
- `../../../tests/new-products-visual.test.mjs`: comprobaciones de aislamiento.

No se modifica el controlador `renderer/bot-module.js`, su configuración,
validadores, llamadas a API ni ningún archivo del backend. Los botones mantienen
sus listeners y sus atributos `hidden`/`disabled`. Los estados de éxito/error y
los enlaces de descarga siguen siendo responsabilidad del controlador original.

## Alcance

Las reglas internas empiezan con `#view-bot`. Las del encabezado y barra lateral
usan `body:has(#view-bot.active)`: al navegar a otro módulo dejan de aplicarse.
El planeta y el robot del dashboard no se modifican.

La tarjeta hero redundante se oculta; su botón de guía NO se elimina. Se mueve
con `append` (sin clonarlo) a Opciones avanzadas. La fecha copia texto del
calendario existente; no agrega solicitudes ni temporizadores.

El componente expone `initializeNewProductsVisuals()` para montaje idempotente,
y el controlador devuelto ofrece `destroy()` para limpiar los observadores,
restaurar la guía y los textos y retirar el calendario/estilo que haya creado.
No debe añadirse lógica del bot a estos archivos.

## Validación

Desde la raíz del repositorio:

```sh
node --test frontend/tests/new-products-visual.test.mjs
```

Comprobación visual recomendada: vista inicial, Opciones avanzadas abiertas,
Excel analizado con mapeo, lote en ejecución con Detener visible, errores largos
y navegación a Leads Deploy/Dashboard. A 1020 px o menos las tarjetas se apilan;
a 700 px o menos el menú se acomoda encima del contenido. No se ocultan acciones
operativas para hacer coincidir la captura.

La prueba del cambio se hizo en Chromium con una página de prueba aislada basada
en la estructura del módulo. No ejecuta automatizaciones ni envía leads reales.
La fecha, el nombre del archivo y los resultados son dinámicos en la aplicación;
no se fijan los valores de la imagen de referencia.
