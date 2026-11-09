# Database migrations

Migration files use the immutable `YYYYMMDDHHMMSS_description.sql` format and are applied transactionally by `db_migrations.apply_migrations` when the existing persistence layer initializes.

Rules:

- Never edit an applied migration; add a new migration.
- Keep files compatible with PostgreSQL and the repository's SQLite test mode.
- Do not include procedural blocks or semicolons inside string literals; the dependency-free runner intentionally supports simple DDL/DML statements.
- Index foreign keys and queue lookup patterns.
- Keep external API calls outside database transactions.
- Production migration execution requires a separately approved deployment.

