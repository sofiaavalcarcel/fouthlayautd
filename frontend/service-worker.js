// Service worker mínimo para evitar solicitudes 404 en el frontend.
// La aplicación no usa caché offline; por eso no interceptamos peticiones.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", () => self.clients.claim());
