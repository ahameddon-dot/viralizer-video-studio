# Viralizer Worldwide Intelligence APIs

These developer APIs use Viralizer's own worldwide public-source discovery.
They do not call, proxy, or mix data from Viralizer MCP.

## Endpoint

`GET https://v3.viralizer.ai/api/v1/hot-topics`

The endpoint returns a normalized worldwide hot-topic feed from Viralizer
Worldwide Intelligence.

## Authentication

Set one or more comma-separated keys on Render:

```text
VIRALIZER_TOPICS_API_KEYS=developer-key-one,developer-key-two
VIRALIZER_TOPICS_API_CACHE_SECONDS=300
```

Send a key using either header:

```http
Authorization: Bearer developer-key-one
```

or:

```http
X-API-Key: developer-key-one
```

Never give a developer the internal MCP token. Give each developer a separate
topic API key so access can be revoked independently.

## Query parameters

| Parameter | Default | Notes |
| --- | --- | --- |
| `category` | empty | Partial, case-insensitive category match |
| `country` | `worldwide` | Supports names and common codes such as `US`, `IN`, `GB` |
| `language` | empty | Partial, case-insensitive language match |
| `search` | empty | Searches title, summary and category |
| `limit` | `20` | Minimum 1, maximum 100 |
| `cursor` | empty | Opaque cursor returned by the previous response |

## Example

```bash
curl "https://v3.viralizer.ai/api/v1/hot-topics?category=technology&country=worldwide&limit=20" \
  -H "Authorization: Bearer developer-key-one"
```

The response includes `api_version`, `generated_at`, `source`, `total`, a
normalized `topics` array, and `next_cursor` when another page is available.

The `source` value is:

```text
Viralizer Worldwide Intelligence
```

## Topic Intelligence

`POST https://v3.viralizer.ai/api/v1/topic-intelligence`

Use the same API-key headers. The JSON body accepts:

| Field | Required | Notes |
| --- | --- | --- |
| `category` | yes | Main category or subject |
| `super_category` | no | Broader taxonomy group |
| `categories` | no | Up to 50 category names |
| `keyword` | no | Additional keyword focus |
| `description` | no | Short discovery context |
| `lens` | no | Entity or intelligence lens |
| `reputation` | no | Reputation/sentiment focus |

The optional `limit` query parameter defaults to 30 and is capped at 100.

```bash
curl -X POST "https://v3.viralizer.ai/api/v1/topic-intelligence?limit=20" \
  -H "Authorization: Bearer developer-key-one" \
  -H "Content-Type: application/json" \
  -d '{
    "category": "Artificial Intelligence",
    "super_category": "Technology",
    "keyword": "enterprise adoption",
    "lens": "companies",
    "reputation": "mixed"
  }'
```

The response contains the normalized `topics`, the exact discovery `queries`,
the normalized `query`, `generated_at`, and the source label
`Viralizer Worldwide Intelligence`.

Interactive OpenAPI documentation is available at `/docs` after deployment.
