# NL2SQL Vanna Oracle

## Admin reports and reviewed training

Configure the admin session in `.env`:

```dotenv
ADMIN_AUTH_USER=admin
ADMIN_AUTH_PASSWORD=use-a-strong-password
ADMIN_SESSION_SECRET=use-a-long-random-secret
ADMIN_SESSION_COOKIE_SECURE=true
```

Set `ADMIN_SESSION_COOKIE_SECURE=true` when using HTTPS/ngrok and `false` for plain
local HTTP. Restart the application and open `/admin`. User 👍/👎 feedback creates a
review candidate; it does not write to Chroma directly. An admin can inspect or edit
the Oracle SQL, run a limited preview, and explicitly approve it from the training queue.

The canonical review and audit state is stored in `data/training.sqlite3`. Chroma remains
the retrieval index. `train.py` now upserts stable baseline records and preserves curated
training approved from the admin page.

## AI activity report API

Each user question is recorded in `logs/ai_report.jsonl`. The report includes:

- question, generated Oracle SQL, final AI answer, model, user, and timestamps;
- total response time, SQL execution time, returned row count, and chart generation;
- tool calls with sensitive arguments redacted, plus tool success/failure and errors;
- aggregate success rate, average and p95 response time, SQL generation rate;
- HITL approvals, rejections, corrections, and approval rate.

Fetch summary metrics and recent requests:

```http
GET /api/reports/ai?start=2026-07-01T00:00:00Z&limit=50
X-API-Key: your-report-api-key
```

Useful filters are `start`, `end`, `success`, `user_id`, `limit` (maximum 500), and `offset`.
Fetch a single record using `GET /api/reports/ai/{report_id}`.

Example browser usage:

```js
const response = await fetch("https://api.example.com/api/reports/ai?limit=25", {
  headers: { "X-API-Key": "your-report-api-key" },
});
if (!response.ok) throw new Error(`Report request failed: ${response.status}`);
const report = await response.json();

console.log(report.summary.success_rate_percent);
console.table(report.items);
```

Configure `REPORT_API_KEY` before exposing the endpoint. If it is empty, application-wide Basic
Auth must be enabled or the endpoint returns `503`. For browser pages on another origin, add the
exact origins to `REPORT_API_CORS_ORIGINS`.

`AI_REPORT_INCLUDE_RESPONSE_TEXT=false` prevents final answers from being retained. Questions and
generated SQL remain in the report because they are the core diagnostic fields. Do not put a
long-lived API key in public browser JavaScript; use a backend or reverse proxy for public pages.
