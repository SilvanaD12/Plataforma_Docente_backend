## Arquitectura del backend

El backend seguirá una arquitectura hexagonal.

- `src/platform5e/domain/` contiene las reglas del proyecto.
- `src/platform5e/application/` contiene los casos de uso y los puertos.
- `src/platform5e/infrastructure/` contiene los adaptadores de API, base de datos y proveedores.
- `src/platform5e/main.py` conecta los servicios con sus adaptadores.

La [constitución](.specify/memory/constitution.md) reúne los acuerdos del equipo.
Las [especificaciones](specs/) describen el alcance de cada cambio.
