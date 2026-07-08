# Scrim Management Deployment

## Recommended Production Setup

Use Vercel for the app and an external Postgres database for permanent data.

```text
User browser
  -> Vercel app/API
  -> External Postgres
```

Local development can continue to use SQLite. Production should set
`SCRIM_DATABASE_URL` to a pooled Postgres connection string. The app uses this
for members, scrim data, and persistent tournament state. If tournament state
should use a separate database, set `STATE_DATABASE_URL`.

## Vercel Environment Variables

```env
SCRIM_DATABASE_URL=postgresql://...
STATE_DATABASE_URL=
STATE_DATABASE_KEY=lol-auction:state
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
