-- ============================================================================
-- 005_members.sql
-- Consolidated members table (final state)
-- Sources: AI_crud migrations 002 + 006 + 023 + 025 + 028 + 037a
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Links (profile_id nullable for pending invites)
    profile_id UUID REFERENCES public.profiles(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,

    -- User info
    name TEXT,
    email TEXT,
    employee_id TEXT,
    department TEXT,
    designation TEXT,

    -- Hierarchy
    hierarchy_level INT,
    reports_to UUID REFERENCES public.members(id) ON DELETE SET NULL,

    -- Delegations
    delegations JSONB DEFAULT '[]',

    -- Extra data
    data JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT true,

    -- Team management (from 006)
    status TEXT DEFAULT 'active',
    is_owner BOOLEAN DEFAULT false,
    invited_by UUID REFERENCES public.members(id) ON DELETE SET NULL,
    invited_at TIMESTAMPTZ DEFAULT NOW(),

    -- Feature access / RBAC (from 023)
    feature_access JSONB DEFAULT '{}',

    -- Invitation tokens (from 025)
    invitation_token TEXT UNIQUE,
    invitation_expires_at TIMESTAMPTZ,

    -- Notification flag (from 028)
    seen BOOLEAN DEFAULT false,

    -- Unit assignment (from 037a)
    unit_id UUID REFERENCES public.units(id) ON DELETE SET NULL,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Constraints
    CONSTRAINT members_status_check CHECK (status IN ('active', 'pending', 'inactive')),
    CONSTRAINT members_email_workspace_unique UNIQUE (email, workspace_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_members_profile ON public.members(profile_id);
CREATE INDEX IF NOT EXISTS idx_members_workspace ON public.members(workspace_id);
CREATE INDEX IF NOT EXISTS idx_members_hierarchy ON public.members(workspace_id, hierarchy_level);
CREATE INDEX IF NOT EXISTS idx_members_reports_to ON public.members(reports_to);
CREATE INDEX IF NOT EXISTS idx_members_active ON public.members(workspace_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_members_email_workspace ON public.members(email, workspace_id);
CREATE INDEX IF NOT EXISTS idx_members_status ON public.members(workspace_id, status);
CREATE INDEX IF NOT EXISTS idx_members_profile_lookup ON public.members(profile_id) WHERE profile_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_members_feature_access ON public.members USING gin (feature_access);
CREATE INDEX IF NOT EXISTS idx_members_unit ON public.members(workspace_id, unit_id);
CREATE INDEX IF NOT EXISTS idx_members_profile_unseen ON public.members(profile_id, seen) WHERE status = 'active' AND seen = false;
CREATE INDEX IF NOT EXISTS idx_members_invitation_token ON public.members(invitation_token) WHERE invitation_token IS NOT NULL;

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.update_members_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_members_updated_at
    BEFORE UPDATE ON public.members
    FOR EACH ROW
    EXECUTE FUNCTION public.update_members_updated_at();
