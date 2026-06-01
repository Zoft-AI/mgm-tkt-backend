-- ============================================================================
-- 006_rules.sql
-- Approval rules per workspace/agent
-- Source: AI_crud/migration/003_create_rules.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    chat_agent_id UUID REFERENCES public."Chat_Agents"(id) ON DELETE CASCADE,

    rule_name TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    category TEXT,

    data JSONB NOT NULL DEFAULT '{}',

    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_rules_workspace ON public.rules(workspace_id);
CREATE INDEX IF NOT EXISTS idx_rules_agent ON public.rules(chat_agent_id);
CREATE INDEX IF NOT EXISTS idx_rules_active ON public.rules(workspace_id, is_active) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_rules_type ON public.rules(workspace_id, rule_type);

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.update_rules_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_rules_updated_at
    BEFORE UPDATE ON public.rules
    FOR EACH ROW
    EXECUTE FUNCTION public.update_rules_updated_at();
