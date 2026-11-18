# QA-13 Limpieza de ramas

## Resultado

Se eliminaron las ramas remotas antiguas integradas. Se revisaron aparte las ramas de HU-038 del frontend, cuyo chat y prueba E2E llegaron a main con los PR #18 y #20, y el revert del backend del PR #39, cerrado sin fusionar.

Al finalizar, el frontend conservó main. El backend conservó main y docs/qa-19-iso25023-scope, asociada al PR #59 abierto al tomar la evidencia. origin/HEAD es una referencia simbólica a main.

Se activó Automatically delete head branches en ambos repositorios.

## Entorno y comprobación

PowerShell en Windows, copias locales D:\Plataforma_Docente_frontend y D:\Plataforma_Docente_backend. Capturas recibidas el 17 de noviembre de 2026, hora de Perú.

En ambos repositorios se ejecutó:

```powershell
git fetch origin --prune
git --no-pager branch -r --merged origin/main
git --no-pager branch -r --no-merged origin/main
```

Tras borrar las ramas verificadas se ejecutó:

```powershell
git fetch origin --prune
git --no-pager branch -r
```

Las tres ramas que requirieron comprobación aparte se eliminaron con:

```powershell
# Desde el frontend
git push origin --delete feat/hu-038-generation-chat test/hu-038-t072

# Desde el backend
git push origin --delete revert-37-feat/hu-038-interpret-generation-request
```

## Evidencias

- frontend-ramas-finales.png
- backend-ramas-finales.png
- frontend-borrado-automatico.png
- backend-borrado-automatico.png

Pendiente registrar el enlace del PR de evidencia en la tarea QA-13 cuando se integre la ampliación de la spec 005 del PR #59.
