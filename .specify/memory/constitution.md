# Constitución de Plataforma 5E

## Principios

### I. Arquitectura hexagonal
El dominio y la aplicación deben mantener sus reglas separadas de los detalles de infraestructura. Los casos de uso se conectan a sus adaptadores mediante puertos. Cada cambio que cruce capas debe explicar la dependencia y pasar las pruebas de arquitectura.

### II. Contrato OpenAPI
OpenAPI es la referencia compartida entre frontend y backend. Un cambio de comportamiento debe mantener alineados el contrato, la implementación, los consumidores y sus pruebas.

### III. Evidencia y aprobación
Las afirmaciones verificables requieren evidencia. Los distractores siguen su regla de fiabilidad. Las exportaciones nuevas requieren recursos aprobados y con verificación vigente. La revisión conserva el vínculo con la versión histórica de las fuentes.

### IV. Aislamiento por docente y unidad
El acceso a material, evidencia y resultados se verifica para el docente autenticado y su unidad. La búsqueda vectorial debe respetar ambos límites. Las pruebas de integración deben comprobar el aislamiento entre dos docentes.

### V. Pruebas y entrega por módulo
Cada módulo define criterios de aceptación y pruebas unitarias e integración cuando corresponda. Los flujos entre módulos se verifican de extremo a extremo. Cada cambio concreto se trabaja en una rama y se revisa mediante PR antes de integrarlo a main.

## Responsables

| Módulo | Responsable |
|---|---|
| Material y evidencia | Sergio Celi |
| Generación | Yan |
| Revisión y exportación | Juan |
| Cuentas y cursos | Silvana Díaz |

Silvana coordina la base técnica compartida. Cada responsable cubre frontend, backend y pruebas según el alcance de su módulo.

## Gobernanza

Los planes deben comprobar el cumplimiento de estos principios antes de implementar. Los cambios de alcance o de principios se registran y revisan con el equipo. Referencia inicial: especificaciones de Plataforma 5E, versión 0.4.

**Versión** 1.0.0
