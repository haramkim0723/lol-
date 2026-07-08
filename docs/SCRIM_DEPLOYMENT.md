# Scrim Management Deployment

## Recommended Production Setup

Use Vercel for the app, external Postgres for relational scrim/member data,
and KV/Redis storage for tournament state.

```text
User browser
  -> Vercel app/API
  -> External Postgres for members/scrims/notices
  -> KV/Redis for auction/tournament state
```

Local development can continue to use SQLite. Production should set
`SCRIM_DATABASE_URL` to a pooled Postgres connection string for members, scrim
data, and notices. Tournament state should use Vercel KV/Upstash via
`KV_REST_API_URL` and `KV_REST_API_TOKEN`. Set `STATE_DATABASE_URL` only if you
intentionally want tournament state in a separate Postgres database.

## Vercel Environment Variables

```env
SCRIM_DATABASE_URL=postgresql://...
STATE_DATABASE_URL=
STATE_DATABASE_KEY=lol-auction:state
KV_REST_API_URL=https://...
KV_REST_API_TOKEN=...
SCRIM_SESSION_SECRET=replace-with-a-long-random-secret
SCRIM_ADMIN_PASSWORD=replace-in-production
SESSION_SECRET=replace-with-a-long-random-secret
```

For roughly 100 concurrent users, use the provider's pooled connection URL. This avoids
serverless function bursts opening too many direct database connections.

## Admin Accounts

The app seeds two admin accounts automatically:

```text
장원혁#ADMIN
서세진#ADMIN
```

Their initial password comes from `SCRIM_ADMIN_PASSWORD`.
