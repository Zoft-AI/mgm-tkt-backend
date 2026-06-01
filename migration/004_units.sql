-- ============================================================================
-- 004_units.sql
-- Business units per workspace (e.g., HC, CI, Malar, SH)
-- Source: AI_crud/migration/037a_create_units_and_alter_members.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.units (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    email_domain TEXT,
    is_active BOOLEAN DEFAULT true,
    data JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE (workspace_id, code)
);

CREATE INDEX IF NOT EXISTS idx_units_workspace ON public.units(workspace_id);
