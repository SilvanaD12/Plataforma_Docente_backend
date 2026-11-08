# Base de datos local (PostgreSQL + pgvector)

Entorno de EN-011: PostgreSQL 17 con la extensión **pgvector 0.8.1**, tabla de fragmentos con embeddings de
**768 dimensiones** (SP-001), índice HNSW por distancia coseno, índice por unidad e índice GIN para búsqueda por
palabras en español. Existe un backend FastAPI con SQLAlchemy. Usa SQLite por defecto; este entorno PostgreSQL se configura aparte. Ver [arquitectura y conexión](../../docs/architecture/overview.md).

## Requisitos

- **Docker Desktop** instalado y **abierto** (el icono de la ballena debe estar activo).
- No hace falta instalar PostgreSQL ni dbmate: se ejecutan en contenedores.

## Primera vez

Desde `backend/`:

```bash
cp .env.example .env                  # variables locales (revisa los comentarios del archivo)
docker compose up -d --wait db        # inicia PostgreSQL con pgvector
docker compose run --rm dbmate up     # aplica las migraciones pendientes
```

Si el puerto 5432 ya está en uso por otro PostgreSQL, cambia `POSTGRES_PORT` (y el puerto de `DATABASE_URL`) en `.env`.

## Verificar la base vectorial

```bash
./database/verification/verify.sh
```

Crea una base temporal, le aplica todas las migraciones, ejecuta `database/verification/verify_vector_store.sql`
y la elimina al terminar. La base de desarrollo no se modifica. Debe terminar con `VERIFICACIÓN EN-011 SUPERADA`.

| Comprobación | Qué demuestra |
|---|---|
| C01 | pgvector instalado (versión), distancia coseno correcta, `vector(768)` rechaza otras dimensiones |
| C02.1 | Top-k filtrado por unidad: devuelve los 3 fragmentos plantados en orden y excluye uno aún más cercano de otra unidad. Muestra el plan que elige PostgreSQL |
| C02.2 | Top-k sin filtro: el `EXPLAIN` usa `fragmento_embedding_hnsw` y el resultado es el esperado |
| C02.3 | Top-k filtrado **por el índice HNSW** (con *iterative scan*): resultado correcto, igual a la búsqueda exacta en el top-3 |
| HU-012 | «pila» encuentra «pilas» (diccionario español) y el índice GIN responde |

Sobre los planes de ejecución:

- Con ~1.000 fragmentos por unidad, PostgreSQL prefiere para la consulta filtrada usar `fragmento_unidad_idx`
  y ordenar de forma **exacta**, porque le resulta más barato. Es correcto. El índice HNSW se usa cuando el conjunto
  a ordenar es grande: consultas sin filtro, por curso o unidades muy grandes.
- El recall@10 del índice frente a la búsqueda exacta con vectores **aleatorios** varía entre 6 y 10 de 10. Es el peor
  caso para un índice aproximado, porque todos los puntos están casi a la misma distancia. Con embeddings reales,
  y si hace falta subiendo `hnsw.ef_search`, debe medirse en EN-013.

## Comandos habituales

| Comando | Qué hace |
|---|---|
| `docker compose run --rm dbmate status` | Lista migraciones aplicadas y pendientes |
| `docker compose run --rm dbmate up` | Aplica las pendientes y actualiza `database/schema.sql` |
| `docker compose run --rm dbmate rollback` | Revierte la última migración (sección `migrate:down`) |
| `docker compose run --rm dbmate new nombre_en_minusculas` | Crea `database/migrations/<fecha>_nombre_en_minusculas.sql` |
| `docker compose exec db psql -U plataforma5e -d plataforma5e` | Consola SQL (usuario y base según tu `.env`) |
| `docker compose stop` | Detiene PostgreSQL conservando los datos |
| `docker compose down -v` | **Borra** el contenedor y los datos locales (empezar de cero) |

## Reglas

- **No editar migraciones ya aplicadas**: crear una nueva con `dbmate new`. Cada archivo tiene `-- migrate:up` y
  `-- migrate:down`.
- `database/schema.sql` lo genera dbmate. No se edita a mano; se sube al repositorio como referencia del esquema actual.
- `.env` no se sube al repositorio (ya está en `.gitignore`). Las variables nuevas se documentan en `.env.example`.

## Estructura actual

| Migración | Contenido |
|---|---|
| `20261005000001_esquema_base.sql` | `curso`, `unidad`, `documento`. **Provisional**: sustituye a EN-002, que aún no existe en el repositorio |
| `20261005000002_base_vectorial.sql` | Extensión `vector`; tabla `fragmento` (documento, unidad, curso, página, orden, texto, `embedding vector(768)`, `modelo_embedding`, `texto_tsv`); índices HNSW coseno, unidad, GIN y documento |

`embedding` y `modelo_embedding` quedan nulos hasta que EN-013 vectorice los fragmentos (la base exige que ambos
estén presentes o ambos ausentes). La consulta prevista para el backend es:

```sql
SET hnsw.iterative_scan = relaxed_order;   -- pgvector ≥ 0.8, mejora el top-k con filtros
SELECT id, texto, pagina, embedding <=> $1 AS distancia
FROM fragmento
WHERE unidad_id = $2
ORDER BY embedding <=> $1
LIMIT $3;
```

Recuerda que con multilingual-e5-base el vector de la consulta se genera con el prefijo `"query: "` y el de los
fragmentos con `"passage: "` (ver `docs/spikes/SP-001-embedding-models.md`).
