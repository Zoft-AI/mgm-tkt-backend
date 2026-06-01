-- ============================================================================
-- 003_hierarchy.sql
-- Approval level definitions per workspace
-- Source: AI_crud/migration/001_create_hierarchy.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.hierarchy (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,

    level INT NOT NULL,
    level_name TEXT NOT NULL,
    reports_to_level INT,

    data JSONB DEFAULT '{}',

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(workspace_id, level)
);

CREATE INDEX IF NOT EXISTS idx_hierarchy_workspace ON public.hierarchy(workspace_id);

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.update_hierarchy_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_hierarchy_updated_at
    BEFORE UPDATE ON public.hierarchy
    FOR EACH ROW
    EXECUTE FUNCTION public.update_hierarchy_updated_at();
