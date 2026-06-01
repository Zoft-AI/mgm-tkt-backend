-- ============================================================================
-- 001_extensions.sql
-- Enable required PostgreSQL extensions
-- Compatible with: RDS PostgreSQL 13+ / Supabase
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
