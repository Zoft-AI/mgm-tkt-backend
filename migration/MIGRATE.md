# Migration Guide -- mgm_tkt_backend

## Prerequisites

- PostgreSQL 13+ (Supabase project or RDS instance)
- `psql` CLI or Supabase SQL Editor access

## File Run Order

Run these files **in order**. Each file is idempotent (`IF NOT EXISTS` / `CREATE OR REPLACE`).

| # | File | What it does |
|---|------|-------------|
| 1 | `001_extensions.sql` | Enables `pg_trgm` and `uuid-ossp` extensions |
| 2 | `002_core_tables.sql` | Creates `profiles`, `Workspaces`, `Chat_Agents`, `Chat_Agent_history` |
| 3 | `003_hierarchy.sql` | Creates `hierarchy` table + trigger |
| 4 | `004_units.sql` | Creates `units` table |
| 5 | `005_members.sql` | Creates `members` table (consolidated) + 12 indexes + trigger |
| 6 | `006_rules.sql` | Creates `rules` table + trigger |
| 7 | `007_requests.sql` | Creates `requests` table (consolidated) + `generate_request_number` trigger |
| 8 | `008_products.sql` | Creates `products` table + GIN indexes |
| 9 | `009_file_attachments.sql` | Creates `file_attachments` table (S3 metadata) |
| 10 | `010_functions.sql` | Creates all DB functions: `create_new_user()`, `link_member_profile()`, RPCs, health check |
| 11 | `011_seed_data.sql` | **TEMPLATE** -- fill with your actual data before running |

## Running via Supabase SQL Editor

1. Open your Supabase project dashboard
2. Go to **SQL Editor**
3. Copy-paste each file's contents in order (001 through 010)
4. Fill in `011_seed_data.sql` with your actual workspace/member/rule data, then run it

## Running via psql (RDS or local)

```bash
export PGHOST=your-db-host
export PGUSER=postgres
export PGDATABASE=mgm_tkt
export PGPASSWORD=your-password

for f in migration/001_extensions.sql \
         migration/002_core_tables.sql \
         migration/003_hierarchy.sql \
         migration/004_units.sql \
         migration/005_members.sql \
         migration/006_rules.sql \
         migration/007_requests.sql \
         migration/008_products.sql \
         migration/009_file_attachments.sql \
         migration/010_functions.sql; do
    echo "Running $f..."
    psql -f "$f"
done

echo "Now edit migration/011_seed_data.sql with your data, then run:"
echo "psql -f migration/011_seed_data.sql"
```

## Tables Created (10)

- `profiles` -- user profiles
- `Workspaces` -- workspace container
- `Chat_Agents` -- chat agents (FK target for requests)
- `Chat_Agent_history` -- conversation logs
- `hierarchy` -- approval levels per workspace
- `units` -- business units per workspace
- `members` -- team members (consolidated: hierarchy, invites, feature_access, units, seen)
- `rules` -- approval routing rules
- `requests` -- tickets/approvals (consolidated: approval_chain, SLA, auto_approve)
- `products` -- product catalog
- `file_attachments` -- S3 file metadata

## Functions Created (6)

- `create_new_user(p_user_id, p_email, p_name)` -- signup: creates profile + workspace + member
- `link_member_profile()` -- trigger: auto-links pending members on profile creation
- `generate_request_number()` -- trigger: auto-generates REQ-YYYY-NNNNN
- `get_requests_approved_by_member()` -- RPC: requests acted on by a member
- `get_requests_approved_by_member_count()` -- RPC: count for pagination
- `get_my_approval_stats()` -- RPC: dashboard stats
- `get_service_status()` -- health check

## Notes

- No RLS policies are created. Access control is handled by FastAPI JWT middleware.
- The `create_new_user()` function is NOT attached as a trigger. Your Python auth service calls it explicitly during signup.
- `link_member_profile()` IS a trigger on `profiles` -- fires automatically on INSERT.
- `generate_request_number()` IS a trigger on `requests` -- fires automatically on INSERT.
