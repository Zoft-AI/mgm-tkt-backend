-- ============================================================================
-- 007_requests.sql
-- Consolidated requests table (final state)
-- Sources: AI_crud migrations 004 + 010 + 017
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_number TEXT UNIQUE,

    -- Scope
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    chat_agent_id UUID NOT NULL REFERENCES public."Chat_Agents"(id) ON DELETE CASCADE,

    -- Rule
    rule_id UUID REFERENCES public.rules(id) ON DELETE SET NULL,

    -- Actors
    raised_by UUID NOT NULL REFERENCES public.members(id),
    raised_to UUID REFERENCES public.members(id),
    current_approver UUID REFERENCES public.members(id),

    -- Content
    subject TEXT NOT NULL,
    description TEXT,
    request_type TEXT DEFAULT 'support',
    category TEXT,
    priority TEXT DEFAULT 'normal',

    -- Request data
    data JSONB DEFAULT '{}',
    attachments JSONB DEFAULT '[]',

    -- Status
    status TEXT DEFAULT 'pending',
    current_level INT,
    required_level INT,

    -- Messages (embedded JSONB array)
    messages JSONB DEFAULT '[]',

    -- History / audit trail (embedded JSONB array)
    history JSONB DEFAULT '[]',

    -- Approval chain (from 017) - [{id, name, status, at}]
    approval_chain JSONB DEFAULT '[]',

    -- Escalation
    escalation_chain JSONB DEFAULT '[]',
    is_emergency BOOLEAN DEFAULT false,
    emergency_reason TEXT,

    -- Override
    is_overridden BOOLEAN DEFAULT false,
    overridden_by UUID REFERENCES public.members(id),
    override_reason TEXT,

    -- Delegation
    approved_by_delegate BOOLEAN DEFAULT false,
    original_approver UUID REFERENCES public.members(id),

    -- SLA
    sla_deadline TIMESTAMPTZ,
    is_sla_breached BOOLEAN DEFAULT false,
    sla_auto_approve BOOLEAN DEFAULT true,
    auto_approved BOOLEAN DEFAULT false,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_requests_workspace_agent ON public.requests(workspace_id, chat_agent_id);
CREATE INDEX IF NOT EXISTS idx_requests_raised_by ON public.requests(raised_by);
CREATE INDEX IF NOT EXISTS idx_requests_raised_to ON public.requests(raised_to);
CREATE INDEX IF NOT EXISTS idx_requests_current_approver ON public.requests(current_approver);
CREATE INDEX IF NOT EXISTS idx_requests_status ON public.requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_created ON public.requests(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_requests_sla ON public.requests(sla_deadline) WHERE is_sla_breached = false;
CREATE INDEX IF NOT EXISTS idx_requests_type ON public.requests(workspace_id, request_type);
CREATE INDEX IF NOT EXISTS idx_requests_priority ON public.requests(workspace_id, priority) WHERE status = 'pending';

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.update_requests_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_requests_updated_at
    BEFORE UPDATE ON public.requests
    FOR EACH ROW
    EXECUTE FUNCTION public.update_requests_updated_at();

-- Auto-generate request_number (REQ-YYYY-NNNNN)
CREATE OR REPLACE FUNCTION public.generate_request_number()
RETURNS TRIGGER AS $$
DECLARE
    year_str TEXT;
    seq_num INT;
BEGIN
    IF NEW.request_number IS NULL THEN
        year_str := to_char(NOW(), 'YYYY');
        SELECT COALESCE(MAX(
            CAST(SUBSTRING(request_number FROM 'REQ-' || year_str || '-(\d+)') AS INT)
        ), 0) + 1
        INTO seq_num
        FROM public.requests
        WHERE request_number LIKE 'REQ-' || year_str || '-%';

        NEW.request_number := 'REQ-' || year_str || '-' || LPAD(seq_num::TEXT, 5, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_generate_request_number
    BEFORE INSERT ON public.requests
    FOR EACH ROW
    EXECUTE FUNCTION public.generate_request_number();
