# Plan de Cuentas y Cursos

[Ficha CC-01](spec.md) · [Tareas y evidencia](tasks.md)

## Arquitectura y reutilización

| Área | Implementación |
| --- | --- |
| Dominio y aplicación | Reutilizar el dominio de cuentas y `AccountService` para reglas de identidad, sesión, pertenencia y cursos. Aislar de Material y Generación la consulta de pertenencia mediante un puerto acordado. |
| Infraestructura | Mantener FastAPI en routers y esquemas, y SQLAlchemy detrás de `TeacherRepositoryPort`. Inyectar las dependencias en `backend/src/platform5e/main.py`. |
| Frontend | Organizar acceso, cursos y unidades en `src/features/auth`, `src/features/courses` y `src/features/units`. Mantener rutas y marco en `src/app` y el cliente HTTP en `src/shared`. |
| Contrato | Usar [OpenAPI](../../docs/api/openapi.json) como referencia. Actualizarlo junto con el cliente y las pruebas cuando cambien rutas, datos o errores. |
| Código de partida | Reutilizar la [API trasladada](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/3) y el [frontend anterior](https://github.com/Yansete/plataforma-5e-frontend/tree/feca57c/src/features/courses) según los casos de CC-01. |

## Contratos de integración

- **Sesión.** `POST /api/v1/accounts`, `POST /api/v1/sessions` y `GET` o `DELETE /api/v1/sessions/current`. El cliente envía `Authorization: Bearer …` en las llamadas privadas.
- **Cursos.** `GET` y `POST /api/v1/courses`, `PUT` y `DELETE /api/v1/courses/{courseId}`. El cliente reenvía los IDs de unidades y resultados existentes que conserva al editar. El servidor asigna los IDs de los elementos nuevos.
- **Unidad.** `/courses/:courseId/units/:unitId` muestra el resumen y comparte `course` y `unit` con las rutas hijas `material`, `generation`, `review` y `export`. Cada responsable implementa la página de su módulo en `src/features/`. Material y Generación acordarán con Cuentas la firma y los errores del puerto de pertenencia. El backend comprueba la identidad y la pertenencia antes de operar.
- **Borrado.** El adaptador actual elimina también registros de descarga. Coordinar con REV-01 una persistencia por docente que conserve esos registros tras borrar el curso. Verificar la limpieza de documentos, fragmentos y vectores con MAT-01, y de recursos, verificación y multimedia con GEN-01 y REV-01. Habilitar el borrado en la interfaz después de verificar ese contrato.

## Verificación y orden de entrega

1. Revisar acceso docente y el flujo de listado, creación, edición y navegación a unidad.
2. Acordar el puerto de pertenencia y el ciclo de vida de los datos con los responsables de los otros módulos.
3. Verificar el borrado coordinado y su historial antes de conectar la acción de interfaz.
4. Ejecutar el recorrido completo en navegador y las pruebas de API con dos cuentas. Repetir las comprobaciones de persistencia relevantes en PostgreSQL.
