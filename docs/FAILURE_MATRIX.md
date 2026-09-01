# Matriz de fallos — jobsdb-wrapper v4 (guest-only)

Cómo responde el cliente a cada condición conocida. Taxonomía en
`http.py:classify_response` / `interpret_body`; toda condición mapea a un
`RequestError.kind` o a una excepción tipada de `models.py`.

| # | Condición | Detección | Retry | Excepción final | Mitigación del usuario |
|---|-----------|-----------|-------|-----------------|------------------------|
| F1 | Timeout / conexión rechazada / DNS | excepción de `curl_cffi` en `post()` | backoff exponencial (base 2s, cap 15s) ×`retries` | `JobsDBError("network…")` | comprobar red/proxy; subir `timeout` |
| F2 | HTTP 403 con página Cloudflare ("Just a moment") | cuerpo HTML + status | 1 retry; si persiste, aborta sin más reintentos | `JobsDBBlockedError` | rotar IP (`JOBSDB_PROXY`), esperar, bajar RPM |
| F3 | HTTP 403/429 sin challenge | status code | backoff ×`retries` | `JobsDBBlockedError` (403) / `JobsDBHTTPError` (otros) | reducir `rate_limit_rpm`; proxy |
| F4 | HTTP 5xx | status code | backoff ×`retries` | `JobsDBHTTPError` | reintentar más tarde |
| F5 | GraphQL `UNSTABLE_QUERY_ERROR` (soft) | `extensions.code` en `errors` | 1 retry con `sessionId` nuevo (`runtime_retry=True` en search) | `JobsDBError` si persiste | transitorio upstream; reintentar |
| F6 | GraphQL error duro (operación inválida, schema drift) | `errors[]` con mensaje ≠ "An error occurred" | no | `JobsDBError("GraphQL error: …")` | correr `jobsdb doctor` para detectar drift |
| F7 | Respuesta 200 sin `data.<op>` | `interpret_body` | no | `JobsDBError` | verificar `operationName`/contrato con `doctor` |
| F8 | Job inexistente o payload vacío en `JobDetail` | `data.jobDetails.job` null | no | `JobsDBError("Job <id> not found…")` | verificar id; puede estar expirado |
| F9 | Bot-score alto (`seek-bot-score ≥ 30`) | header de respuesta | — (no lanza) | — | el `RateLimiter` ensancha el intervalo (×1.5, cap 3×) y recupera gradualmente |
| F10 | 0 resultados | `pagination.resultCount == 0` | — | — | no es error: `SearchResult(total=0, jobs=[])` |
| F11 | Payload de búsqueda cambia de forma (drift) | KeyError explícito/None-guard en mapeo | no | `JobsDBError` o campos vacíos | `jobsdb doctor` valida 7 sondas del contrato en vivo |

## Semántica de reintentos

- `retries` (default 3) aplica a F1/F3/F4; cada intento duerme
  `min(2^attempt + jitter, 15s)`.
- F2 (challenge Cloudflare) aborta tras **un** intento: reintentar contra un
  challenge activo solo empeora la reputación de la IP.
- F5 reintenta una vez con `sessionId` regenerado — el backend SEEK rechaza
  sesiones de búsqueda viejas de forma intermitente.
- El `RateLimiter` es thread-safe (lock interno); `adapt()` se llama con los
  headers de cada respuesta para ajustar el intervalo.

## Comprobación de contrato en vivo

```bash
jobsdb doctor   # exit 0 = contrato sano; exit 1 = drift detectado (ver summary)
```
