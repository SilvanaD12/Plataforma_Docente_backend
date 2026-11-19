# Evidencia de Dominio Propio con HTTPS — QA-12

- **Tarea:** QA-12 (`specs/005-atributos-calidad/tasks.md`)
- **Tipo:** Infraestructura / Portabilidad y Seguridad (ISO/IEC 25010)
- **Dominio registrado:** `plataformadocente.dev`
- **Fecha y hora de comprobación:** 18 de noviembre de 2026, 21:21:07 a 21:22:24 GMT-05:00 (19 de noviembre de 2026, 02:21:07 a 02:22:24 UTC)
- **Responsables:** Juan (Backend) y Yan (Frontend)

---

## 1. Configuración de Infraestructura

1. **Registro del Dominio:**
   - Adquirido en Name.com a través del GitHub Student Developer Pack a nombre de un integrante del equipo.
   - Duración: 1 año, con renovación automática desactivada.

2. **Asignación de Entornos:**
   - **Frontend (Vercel):** `https://plataformadocente.dev` (producción) y `https://www.plataformadocente.dev` (redirección 308).
   - **Backend API (Render):** `https://api.plataformadocente.dev` (servicio `plataforma-docente-api.onrender.com`).

---

## 2. Comprobaciones Reales en Producción

### 2.1. Resolución DNS

#### `Resolve-DnsName plataformadocente.dev`
```text
Name                                           Type   TTL   Section    IPAddress                                
----                                           ----   ---   -------    ---------                                
plataformadocente.dev                          A      300   Answer     216.198.79.1                             
```

#### `Resolve-DnsName www.plataformadocente.dev`
```text
Name                           Type   TTL   Section    NameHost                                                        
----                           ----   ---   -------    --------                                                        
www.plataformadocente.dev      CNAME  300   Answer     57ee545a411b118f.vercel-dns-017.com                             

Name       : 57ee545a411b118f.vercel-dns-017.com
QueryType  : A
TTL        : 300
Section    : Answer
IP4Address : 216.198.79.65

Name       : 57ee545a411b118f.vercel-dns-017.com
QueryType  : A
TTL        : 300
Section    : Answer
IP4Address : 64.29.17.65
```

#### `Resolve-DnsName api.plataformadocente.dev`
```text
Name                           Type   TTL   Section    NameHost                                                        
----                           ----   ---   -------    --------                                                        
api.plataformadocente.dev      CNAME  282   Answer     plataforma-docente-api.onrender.com                             
plataforma-docente-api.onrende CNAME  282   Answer     gcp-us-west1-1.origin.onrender.com                              
r.com                                                                                                                  
gcp-us-west1-1.origin.onrender CNAME  282   Answer     gcp-us-west1-1.origin.onrender.com.cdn.cloudflare.net           
.com                                                                                                                   

Name       : gcp-us-west1-1.origin.onrender.com.cdn.cloudflare.net
QueryType  : A
TTL        : 287
Section    : Answer
IP4Address : 216.24.57.18

Name       : gcp-us-west1-1.origin.onrender.com.cdn.cloudflare.net
QueryType  : A
TTL        : 287
Section    : Answer
IP4Address : 216.24.57.16
```

---

### 2.2. Comprobaciones de Redirección y Certificados HTTPS

#### `curl.exe -sS -I http://api.plataformadocente.dev/health`
```http
HTTP/1.1 301 Moved Permanently
Date: Thu, 19 Nov 2026 02:21:32 GMT
Content-Type: text/html; charset=utf-8
Connection: keep-alive
Location: https://api.plataformadocente.dev/health
cf-cache-status: DYNAMIC
Server: cloudflare
CF-RAY: a5cbbdf7dde5d8eb-SCL
alt-svc: h3=":443"; ma=86400
```

#### `curl.exe -sS -i https://api.plataformadocente.dev/health`
```http
HTTP/1.1 200 OK
Date: Thu, 19 Nov 2026 02:21:39 GMT
Content-Type: application/json
Transfer-Encoding: chunked
Connection: keep-alive
cf-cache-status: DYNAMIC
content-security-policy: frame-ancestors 'none'
referrer-policy: strict-origin-when-cross-origin
rndr-id: 832dca9d-90b0-4c02
Server: cloudflare
vary: Origin
vary: Accept-Encoding
x-content-type-options: nosniff
x-render-origin-server: uvicorn
CF-RAY: a5cbbe207cc8a19e-SCL
alt-svc: h3=":443"; ma=86400

{"status":"ok"}
```

#### `curl.exe -sS -I https://plataformadocente.dev`
```http
HTTP/1.1 200 OK
Accept-Ranges: bytes
Access-Control-Allow-Origin: *
Age: 20943
Cache-Control: public, max-age=0, must-revalidate
Content-Disposition: inline
Content-Length: 916
Content-Type: text/html; charset=utf-8
Date: Thu, 19 Nov 2026 02:21:56 GMT
Etag: "87caeb51ddd4d205e4a335c989bfe409"
Last-Modified: Wed, 18 Nov 2026 20:32:53 GMT
Server: Vercel
Strict-Transport-Security: max-age=63072000
X-Vercel-Cache: HIT
X-Vercel-Id: gru1::b9wzl-1795054916843-ca1754aade54
```

#### `curl.exe -sS -I http://plataformadocente.dev`
```http
HTTP/1.0 308 Permanent Redirect
Content-Type: text/plain
Location: https://plataformadocente.dev/
Refresh: 0;url=https://plataformadocente.dev/
server: Vercel
```

---

### 2.3. Comprobación Preflight CORS en la API

#### `curl.exe -sS -i -X OPTIONS https://api.plataformadocente.dev/api/v1/courses -H "Origin: https://plataformadocente.dev" -H "Access-Control-Request-Method: GET"`
```http
HTTP/1.1 200 OK
Date: Thu, 19 Nov 2026 02:22:14 GMT
Content-Type: text/plain; charset=utf-8
Transfer-Encoding: chunked
Connection: keep-alive
access-control-allow-methods: DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT, QUERY
access-control-allow-origin: https://plataformadocente.dev
access-control-max-age: 600
cf-cache-status: DYNAMIC
content-security-policy: frame-ancestors 'none'
referrer-policy: strict-origin-when-cross-origin
rndr-id: 358d9a18-7239-4622
Server: cloudflare
vary: Origin, Access-Control-Request-Method, Access-Control-Request-Headers, Access-Control-Request-Private-Network
vary: Accept-Encoding
x-content-type-options: nosniff
x-render-origin-server: uvicorn
CF-RAY: a5cbbefa999313b4-SCL
alt-svc: h3=":443"; ma=86400

OK
```

---

### 2.4. Inspección del Bundle JavaScript del Frontend

Descarga del HTML de `https://plataformadocente.dev` e inspección del script `/assets/index-DAbs7n8y.js` (196 933 bytes):

- Contiene `api.plataformadocente.dev`: **False**
- Contiene `onrender.com`: **True** (`https://plataforma-docente-api.onrender.com`)
- **Diagnóstico:** El backend ya tiene configurado el dominio personalizado y la cabecera CORS correspondiente. En el frontend, Vite fija la variable de entorno `VITE_API_URL` en tiempo de construcción (*build-time*). Por lo tanto, el frontend requiere que Yan actualice la variable `VITE_API_URL=https://api.plataformadocente.dev` en el panel de Vercel y ejecute un nuevo despliegue (*redeploy*) para que el bundle apunte al nuevo subdominio.

---

## 3. Matriz de Cumplimiento de Criterios QA-12

| Criterio | Resultado Observado | ¿Cumple? |
| :--- | :--- | :---: |
| **Certificado SSL/TLS válido en ambos** | `plataformadocente.dev` y `api.plataformadocente.dev` responden con HTTPS válido (Cloudflare y Vercel) sin advertencias de certificado | **Sí** |
| **Endpoint `/health` responde 200 por HTTPS** | `GET https://api.plataformadocente.dev/health` retorna HTTP 200 con `{"status":"ok"}` | **Sí** |
| **Redirección permanente HTTP a HTTPS** | `http://api.plataformadocente.dev/health` retorna `301 Moved Permanently`; `http://plataformadocente.dev` retorna `308 Permanent Redirect` | **Sí** |
| **Cabecera CORS para el dominio oficial** | Preflight `OPTIONS` desde `https://plataformadocente.dev` devuelve `access-control-allow-origin: https://plataformadocente.dev` | **Sí** |
| **JS del frontend apunta a la API nueva** | El bundle `index-DAbs7n8y.js` en Vercel aún referencia la URL anterior (`onrender.com`). Pendiente de redeploy con `VITE_API_URL` | **No** (FE pendiente) |
| **Dirección `.vercel.app` fuera de repositorios** | No existen ocurrencias de `.vercel.app` en código ni documentación vigente del backend | **Sí** |

---

## 4. Capturas de Pantalla de Respaldo

Las siguientes capturas de pantalla serán incorporadas en esta carpeta:

1. `dns-name-com.png`: Panel de administración DNS de Name.com con los registros `A @`, `CNAME www` y `CNAME api`.
2. `render-custom-domain.png`: Panel de configuración de Render mostrando el dominio `api.plataformadocente.dev` verificado con TLS activo.
3. `vercel-domains.png`: Panel de Vercel con los dominios `plataformadocente.dev` y `www.plataformadocente.dev` asignados al proyecto.
4. `frontend-consola.png`: Consola de desarrollador del navegador web en `https://plataformadocente.dev` sin advertencias de contenido mixto ni errores de CORS.
