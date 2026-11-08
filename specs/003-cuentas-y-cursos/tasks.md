# Tareas de Cuentas y Cursos

[Ficha CC-01](spec.md) · [Plan](plan.md)

## Trabajo integrado

- [x] T001 [BE] Mantener los contratos base de cuentas, sesión y cursos para listar, crear y editar. Casos CC-C1 a CC-C7. [Base integrada](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/3).
- [x] T002 [BE] Agregar una prueba HTTP con dos docentes que cubra listado, edición y eliminación de un curso ajeno. Caso CC-C8. [Prueba integrada](https://github.com/SilvanaD12/Plataforma_Docente_backend/pull/4).

- [x] T003 [FE] Implementar registro, inicio, restauración y cierre de sesión. Casos CC-C1 a CC-C4. [PR de acceso docente](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/1).
- [x] T004 [FE] Listar cursos, mostrar el detalle y abrir unidades. Compartir `course` y `unit` con las cuatro rutas hijas. Casos CC-C5 y CC-C8. [PR de cursos](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/2).
- [x] T005 [FE] Crear un curso con una o más unidades y mostrar los conflictos de código. Casos CC-C5 y CC-C6. [PR de cursos](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/2).
- [x] T006 [FE] Editar un curso, mantener sus IDs y abrir las unidades guardadas. Caso CC-C7. [PR de cursos](https://github.com/SilvanaD12/Plataforma_Docente_frontend/pull/2). La edición se comprobó también en el navegador local.

## Pendientes de coordinación e integración

- [ ] T007 [BE] Acordar e implementar el puerto de pertenencia con MAT-01 y GEN-01. Probar unidad propia, ajena e inexistente. Casos CC-C8 y CC-C10.
- [ ] T008 [BE] Coordinar el borrado de asociados con MAT-01, GEN-01 y REV-01 y conservar el registro de descarga por docente. Verificar persistencia en PostgreSQL. Caso CC-C9.
- [ ] T009 [FE] Agregar confirmación, resultado y manejo de errores de la eliminación después de verificar T008. Caso CC-C9.
- [ ] T010 [E2E] Registrar una cuenta, crear un curso, editarlo, reabrir su unidad, cerrar sesión y volver a entrar. Incluir evidencia de los casos CC-C1 a CC-C8 y de la conservación de IDs.
- [ ] T011 [E2E] Eliminar un curso de prueba con datos asociados y comprobar que el registro de descarga sigue disponible para su docente. Depende de T008 y T009. Caso CC-C9.
