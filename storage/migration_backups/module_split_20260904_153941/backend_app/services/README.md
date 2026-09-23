# Servicios de aplicación

Esta capa concentra reglas de negocio y adaptadores: dashboard, IA, reportes Excel, mapeo de hojas, validación PDP, rotación de programas y asignación de leads. Los servicios reciben dependencias explícitas y no deben depender del DOM ni de objetos FastAPI salvo que sea estrictamente necesario.
