# Cuentas y Cursos

**Ficha** CC-01

**Responsable** Silvana Díaz

**Estado** En revisión

**Referencias** [Constitución de Plataforma 5E](../../.specify/memory/constitution.md), [OpenAPI](../../docs/api/openapi.json), [plan](plan.md) y [tareas](tasks.md).

## Objetivo y alcance

Permitir que un docente cree su cuenta, gestione su sesión y organice sus cursos, unidades y resultados de aprendizaje. Los demás módulos comparten el contexto de una unidad y validan el acceso en el backend. La recuperación de contraseña, los roles adicionales y la redescarga desde el historial se reservan para entregas posteriores.

## Historia de acceso docente

Como docente, quiero registrarme e iniciar sesión para acceder a mis cursos.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| CC-C1 | Registro un nombre, correo y contraseña válidos | Se crea la cuenta y se inicia una sesión. Se guarda una huella de contraseña con sal y la respuesta omite la contraseña. |
| CC-C2 | Registro un correo ya existente con espacios o mayúsculas distintos | La API devuelve un conflicto y conserva una sola cuenta. |
| CC-C3 | Uso credenciales incorrectas o un token ausente o vencido | La API rechaza el acceso y la interfaz permite volver a iniciar sesión. |
| CC-C4 | Cierro sesión e intento reutilizar el token anterior | La API rechaza el token revocado. |

## Historia de gestión de cursos

Como docente, quiero organizar mis cursos y unidades para preparar el material y los recursos de clase.

| Caso | Dado y cuando | Entonces |
| --- | --- | --- |
| CC-C5 | Creo un curso con código, nombre, periodo y al menos una unidad | Aparece en mi lista con las unidades y los datos opcionales ingresados, como sumilla, logro y resultados. |
| CC-C6 | Repito el código de un curso de mi cuenta | La API devuelve un conflicto. Otra cuenta puede usar ese código en su propio espacio. |
| CC-C7 | Edito un curso y sus unidades existentes y añado otra unidad | Se conservan los IDs de las unidades y de los resultados existentes que se mantienen. Las unidades y los resultados nuevos reciben IDs propios. |
| CC-C8 | Intento leer, editar o eliminar un curso ajeno o usar una unidad ajena | La API rechaza el acceso sin exponer ni modificar datos de la otra cuenta. |
| CC-C9 | Confirmo la eliminación de un curso propio | Se eliminan curso, unidades, documentos, fragmentos, vectores, recursos, verificaciones y multimedia asociados. Se conserva el registro de descarga por docente con fecha, formato, archivo, curso y unidad. |
| CC-C10 | Material o Generación consulta el acceso a una unidad | Cuentas confirma la pertenencia al docente autenticado. Una unidad ajena o inexistente produce un rechazo que omite sus datos. |

## Requisitos funcionales

- **CC-R1.** Validar los datos de registro, normalizar el correo y hacer cumplir su unicidad.
- **CC-R2.** Consultar el perfil autenticado, emitir sesiones con caducidad y revocarlas al salir. Mantener como punto de partida la duración de ocho horas.
- **CC-R3.** Derivar la identidad del token y validar la pertenencia en el backend. Proveer un puerto de pertenencia a Material y Generación.
- **CC-R4.** Listar, crear, editar y eliminar cursos propios. Mantener el código único por docente.
- **CC-R5.** Conservar IDs de unidades existentes y de resultados mantenidos al editar. El backend rechaza que se omitan o sustituyan las unidades guardadas.
- **CC-R6.** Pedir confirmación al eliminar. Coordinar el borrado de datos asociados y la conservación del registro de descargas con REV-01.
- **CC-R7.** Mantener alineados OpenAPI, el cliente y las pruebas.

## Criterios de éxito

- Verificar los casos CC-C1 a CC-C10 y enlazar su evidencia en [las tareas](tasks.md).
- Completar un recorrido de registro, creación, edición, reapertura de unidad y cierre de sesión en el navegador.
- Comprobar el aislamiento con dos cuentas y demostrar la conservación de IDs al editar.
- Después de borrar un curso, comprobar que no quedan datos asociados y que su registro de descarga sigue disponible para su docente.
