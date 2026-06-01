# RDS Migration Notes -- mgm_tkt_backend

When you migrate from Supabase to AWS RDS PostgreSQL, the following code changes are required. The migration SQL files (001-011) are already RDS-compatible (no RLS, no auth.uid(), no storage.buckets).

---

## 1. Database Connection Layer

**File:** `utils/database.py`

**Current (Supabase):**
- Uses `supabase-py` client (`create_client(url, key)`)
- Two clients: standard (anon key) and admin (service_role key)
- Queries use PostgREST syntax: `supabase.table("members").select("*").eq("id", x).execute()`
- RPCs called via: `supabase.rpc("function_name", params).execute()`

**Change to (RDS):**
- Replace `supabase-py` with `psycopg2` (sync) or `asyncpg` (async) connection pool
- Use raw SQL or an ORM like SQLAlchemy
- Example connection pool setup:

```python
import psycopg2
from psycopg2 import pool

class DatabaseManager:
    def __init__(self):
        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=5,
            maxconn=20,
            host=os.environ.get("RDS_HOST"),
            port=os.environ.get("RDS_PORT", 5432),
            dbname=os.environ.get("RDS_DATABASE"),
            user=os.environ.get("RDS_USER"),
            password=os.environ.get("RDS_PASSWORD"),
            sslmode="require"
        )
```

**Impact:** This is the biggest change. Every repository file calls `get_supabase_admin_client()` and uses PostgREST syntax. All queries need rewriting.

---

## 2. Repository Layer (all 3 files)

**Files:**
- `db/workspace_repository.py`
- `db/request_repository.py`
- `db/member_repository.py`

**Current (Supabase PostgREST):**
```python
supabase.table("members").select("*").eq("workspace_id", ws_id).execute()
supabase.table("requests").insert(data).execute()
supabase.table("members").update(data).eq("id", member_id).execute()
supabase.rpc("get_my_approval_stats", {"p_agent_id": agent_id, "p_member_id": member_id}).execute()
```

**Change to (RDS raw SQL):**
```python
cursor.execute("SELECT * FROM members WHERE workspace_id = %s", (ws_id,))
cursor.execute("INSERT INTO requests (...) VALUES (%s, %s, ...)", (values))
cursor.execute("UPDATE members SET ... WHERE id = %s", (member_id,))
cursor.execute("SELECT * FROM get_my_approval_stats(%s, %s)", (agent_id, member_id))
```

**Checklist for each repository:**
- [ ] Replace `.table("X").select(...)` with `SELECT` SQL
- [ ] Replace `.table("X").insert(...)` with `INSERT` SQL
- [ ] Replace `.table("X").update(...)` with `UPDATE` SQL
- [ ] Replace `.table("X").delete(...)` with `DELETE` SQL
- [ ] Replace `.rpc("fn", params)` with `SELECT * FROM fn(params)` SQL
- [ ] Replace `.eq()`, `.in_()`, `.order()`, `.limit()` chains with SQL `WHERE`, `IN`, `ORDER BY`, `LIMIT`
- [ ] Handle `response.data` -> `cursor.fetchall()` / `cursor.fetchone()`
- [ ] Add proper connection/cursor management (context managers, connection pooling)

---

## 3. Authentication Service

**File:** `services/auth.py`

**Current (Supabase):**
- Uses Supabase Auth (`supabase.auth.sign_in_with_password()`, `supabase.auth.sign_out()`)
- JWT issued by Supabase Auth service
- Google OAuth via Supabase (`supabase.auth.sign_in_with_oauth()`)
- `create_new_user` trigger fires automatically on `auth.users` INSERT

**Change to (RDS):**
- Implement your own JWT issuance (using `python-jose` -- already in requirements)
- Replace Supabase Auth with either:
  - AWS Cognito for managed auth
  - Custom auth service with bcrypt password hashing + JWT tokens
  - Keep Supabase Auth as a standalone service (it can work with external DB)
- Call `create_new_user()` as a DB function explicitly after user registration:
  ```python
  cursor.execute("SELECT create_new_user(%s, %s, %s)", (user_id, email, name))
  ```
- Google OAuth: use `authlib` or `python-social-auth` directly instead of Supabase OAuth

---

## 4. Storage Operations

**File:** `utils/storage_operations.py`

**Current (Supabase):**
- Uses `supabase.storage.from_("bucket_name")` for upload/download/move/remove/get_public_url
- Two buckets: `kayzen_chat_files`, `ticket_attachments`

**Change to (RDS + S3):**
- Replace all `supabase.storage` calls with `boto3` S3 operations
- You already have `boto3` in `requirements.txt`
- Add `file_attachments` table queries for metadata tracking (table created in `009_file_attachments.sql`)

```python
import boto3

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    region_name=os.environ.get("AWS_REGION", "ap-south-1")
)

# Upload
s3.upload_fileobj(file, bucket, key)

# Download URL (presigned)
url = s3.generate_presigned_url('get_object', Params={'Bucket': bucket, 'Key': key}, ExpiresIn=3600)

# Delete
s3.delete_object(Bucket=bucket, Key=key)
```

**Function mapping:**

| Supabase storage call | S3 equivalent |
|-----------------------|---------------|
| `storage.from_(bucket).upload(path, file)` | `s3.upload_fileobj(file, bucket, key)` |
| `storage.from_(bucket).get_public_url(path)` | `s3.generate_presigned_url(...)` |
| `storage.from_(bucket).download(path)` | `s3.get_object(Bucket=b, Key=k)['Body'].read()` |
| `storage.from_(bucket).move(from, to)` | `s3.copy_object(...)` + `s3.delete_object(...)` |
| `storage.from_(bucket).remove([path])` | `s3.delete_object(Bucket=b, Key=k)` |

---

## 5. Subscription / Agent Limit Checks

**File:** `utils/database.py` (functions `check_agent_limit`, `validate_subscription`)

**Current:** These functions query `subscriptions`, `subscription_type`, and `Phone_Agents` tables which we excluded from the migration.

**Change to (RDS):**
- Since subscription tables are excluded, either:
  - Remove these functions entirely (hardcode limits or make them config-driven)
  - Or create a simplified `app_config` table with workspace-level limits
- The `check_agent_limit` function references `Phone_Agents` table -- remove that reference

---

## 6. Environment Variables

**Current `.env` (Supabase):**
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...
SERVICE_ROLE_KEY=eyJ...
```

**New `.env` (RDS):**
```
RDS_HOST=your-instance.xxx.ap-south-1.rds.amazonaws.com
RDS_PORT=5432
RDS_DATABASE=mgm_tkt
RDS_USER=postgres
RDS_PASSWORD=your-password
RDS_SSL_MODE=require

AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=xxx
AWS_REGION=ap-south-1
AWS_S3_BUCKET=mgm-ticket-attachments
```

---

## 7. Requirements Changes

**Remove (Supabase-specific):**
```
supabase==2.10.0
gotrue==2.10.0
postgrest==0.18.0
realtime==2.0.6
supafunc==0.7.0
storage3==0.9.0
```

**Add (RDS):**
```
psycopg2-binary==2.9.9
# OR for async:
asyncpg==0.29.0
sqlalchemy==2.0.25  # optional, if using ORM
```

**Keep:**
```
boto3==1.35.0       # already present, for S3
python-jose==3.3.0  # already present, for JWT
redis==5.2.0        # stays the same
```

---

## 8. Migration Priority Order

When you're ready to switch to RDS, tackle in this order:

1. **utils/database.py** -- Replace Supabase client with psycopg2 pool (everything depends on this)
2. **db/*.py** (3 repository files) -- Rewrite queries from PostgREST to raw SQL
3. **services/auth.py** -- Replace Supabase Auth with custom JWT or Cognito
4. **utils/storage_operations.py** -- Replace Supabase storage with S3 boto3
5. **utils/database.py** -- Remove/simplify `check_agent_limit` and `validate_subscription`
6. **requirements.txt** -- Swap packages
7. **.env** -- Update environment variables

---

## 9. What Stays the Same (No Changes Needed)

- `app.py` -- FastAPI app, middleware, CORS, routes (no Supabase dependency)
- `api/*.py` -- Endpoint definitions (they call services, not DB directly)
- `services/workspace_service.py`, `services/request_service.py`, `services/member_service.py` -- Business logic layer (calls repositories, not Supabase directly)
- `utils/sanitize.py`, `utils/security.py`, `utils/common.py`, `utils/global_error_handler.py` -- Pure utility code
- `utils/email_service.py` -- Email logic (no Supabase dependency)
- `config.py` -- Environment config
- Redis caching -- Stays identical
