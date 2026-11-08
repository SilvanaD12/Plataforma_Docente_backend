# Resource catalog (HU-006)

`GET /api/v1/resource-types` publishes the 18 supported resource types in teaching order. It is public metadata:
no session, teacher records or model calls are needed. Swagger documents the response at `/docs`.

Each entry contains `id`, `name`, `singular`, `count` (singular/plural), `stage`, `group`, `format` and `hasOptions`.
Stored identifiers, Spanish labels, grouping and generation options are preserved.

The source is `domain/generation/resource_catalog.py`. `resource_formats.py` derives the stage/format map used
by generation, review and exporters from it. The application query `ListResourceTypesUseCase` is exposed by an
HTTP adapter; the composition root only wires these pieces. No database migration is needed.

The frontend loads this endpoint before generation, review and export. `resourceCatalog.ts` now contains
types, validation and formatting helpers, with no production list of resource types. A failed or malformed response
shows an error and a retry button; it never silently restores an outdated hardcoded catalog. Material upload and
course management remain available independently. The catalog is reused during the current page session.

The fixture under `frontend/src/test/` is test-only. A backend contract test compares it with the HTTP schema so
the existing labels and metadata cannot drift unnoticed. It is not imported by the production application.

## Validation

- Backend: `python -m pytest`.
- Frontend: `npm run typecheck`, `npm test`, `npm run build`, `npm run test:e2e`.
- The catalog E2E test forces a first-request failure, retries, and verifies that modified labels returned by the
  server appear in the options and generation button. Existing E2E tests cover generation, review and export.
- Regenerate `docs/api/openapi.json` with `python scripts/export_openapi.py` after changing the contract.

## Deployment

Deploy the backend endpoint before the frontend that consumes it. If the frontend reaches an older backend,
the catalog request fails visibly and can be retried after the backend deployment. Evidence belongs in Notion.
