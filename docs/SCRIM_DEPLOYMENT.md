# Scrim Management Deployment

## Recommended Production Setup

Use Vercel for the app and Neon Postgres for permanent scrim data.

```text
User browser
  -> Vercel app/API
  -> Neon Postgres
```

Local development can continue to use SQLite. Production should set
`SCRIM_DATABASE_URL` to a Neon pooled Postgres connection string.

## Vercel Environment Variables

```env
SCRIM_DATABASE_URL=postgresql://...
SCRIM_SESSION_SECRET=replace-with-a-long-random-secret
SCRIM_ADMIN_PASSWORD=replace-in-production
SESSION_SECRET=replace-with-a-long-random-secret
```

For roughly 100 concurrent users, use Neon's pooled connection URL. This avoids
serverless function bursts opening too many direct database connections.

## Admin Accounts

The app seeds two admin accounts automatically:

```text
장원혁#ADMIN
서세진#ADMIN
```

Their initial password comes from `SCRIM_ADMIN_PASSWORD`.
