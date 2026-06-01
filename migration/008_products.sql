-- ============================================================================
-- 008_products.sql
-- Product catalog for purchase rules
-- Source: AI_crud/migration/026_create_products_table.sql
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    chat_agent_id UUID REFERENCES public."Chat_Agents"(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    cost NUMERIC NOT NULL DEFAULT 0,
    aliases JSONB DEFAULT '[]'::jsonb,
    category TEXT DEFAULT 'General',
    fields JSONB DEFAULT '[]'::jsonb,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_products_workspace_agent
    ON public.products(workspace_id, chat_agent_id) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_products_category
    ON public.products(workspace_id, chat_agent_id, category) WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_products_name_search
    ON public.products USING gin (name gin_trgm_ops);

CREATE INDEX IF NOT EXISTS idx_products_aliases
    ON public.products USING gin (aliases jsonb_path_ops);
