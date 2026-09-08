# Postgres over SQLite for the ingestion store

Data volume here is small enough that SQLite would suffice on size alone. Postgres was chosen anyway for its `ON CONFLICT DO UPDATE` upsert semantics (central to the idempotent-ingestion design) and stricter typing, and because it's the more portfolio-credible choice for a project whose headline claim is systems-engineering discipline.
