## Arquitectura del backend

El backend seguirá una arquitectura hexagonal.

- `backend/src/platform5e/domain/` contiene las reglas del proyecto.
- `backend/src/platform5e/application/` contiene los casos de uso y los puertos.
- `backend/src/platform5e/infrastructure/` contiene los adaptadores de API, base de datos y proveedores.
- `backend/src/platform5e/main.py` conecta los servicios con sus adaptadores.

La [constitución](.specify/memory/constitution.md) reúne los acuerdos del equipo.
Las [especificaciones](specs/) describen el alcance de cada cambio.
