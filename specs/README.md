# Especificaciones de Plataforma 5E

La [constitución](../.specify/memory/constitution.md) y esta carpeta son la referencia compartida de los repositorios de backend y [frontend](https://github.com/SilvanaD12/Plataforma_Docente_frontend).

| Módulo | Responsable | Carpeta |
| --- | --- | --- |
| REV-01 · Revisión y Exportación | Juan | [001-revision-citas](001-revision-citas/) |
| GEN-01 · Generación | Yan | [002-generacion-multiple](002-generacion-multiple/) |
| CC-01 · Cuentas y Cursos | Silvana Díaz | [003-cuentas-y-cursos](003-cuentas-y-cursos/) |
| MAT-01 · Material y Evidencia | Sergio Celi | Carpeta por registrar con el responsable |

Cada módulo mantiene `spec.md` para requisitos y criterios de aceptación, `plan.md` para arquitectura y contratos, y `tasks.md` para implementación y verificación. Las tareas indican `[BE]`, `[FE]` o `[E2E]`. Cada PR enlaza la ficha y las tareas que cubre. Si un cambio cruza repositorios, enlacen ambos PR y actualicen juntos la especificación y el contrato OpenAPI.

Al usar las herramientas de Spec Kit con una rama de módulo existente, ejecuten la planificación desde la raíz del backend y seleccionen la carpeta correspondiente. Para CC-01 en PowerShell:

```powershell
$env:SPECIFY_FEATURE_DIRECTORY = 'specs/003-cuentas-y-cursos'
```

Para implementar una tarea `[FE]`, trabajen en la rama del módulo en el repositorio del frontend y consulten el plan y las tareas de la carpeta compartida.
