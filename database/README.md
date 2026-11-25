# Database operations

SQLAlchemy models are in `apps/api/models.py`; ordered PostgreSQL migrations are in `database/migrations/`.

## Fresh staging database

```bash
createdb gold_bot_staging
for migration in database/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$migration"
done
```

Set `DATABASE_URL` to the staging PostgreSQL connection before running the command. For a production database that already contains tables, do not replay `0001_initial_schema.sql`; inspect and baseline the existing schema first.

Development mode may use `create_all()` to create a local SQLite schema. Production defaults to `AUTO_CREATE_DB=false` and requires reviewed migrations. Back up and test restoration before applying schema changes.
