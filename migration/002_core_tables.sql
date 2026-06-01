-- ============================================================================
-- 002_core_tables.sql
-- Core tables: profiles, Workspaces, Chat_Agents, Chat_Agent_history
-- These are FK targets for the ticket system tables
-- ============================================================================

-- 1. profiles
CREATE TABLE IF NOT EXISTS public.profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    email TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_email ON public.profiles(email);

-- 2. Workspaces
CREATE TABLE IF NOT EXISTS public."Workspaces" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_name TEXT NOT NULL,
    profile_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT (NOW() AT TIME ZONE 'utc')
);

CREATE INDEX IF NOT EXISTS idx_workspaces_profile ON public."Workspaces"(profile_id);

-- 3. Chat_Agents (minimal columns needed as FK target for requests/rules/products)
CREATE TABLE IF NOT EXISTS public."Chat_Agents" (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    profile_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    bot_name TEXT,
    description TEXT,
    workspace_id UUID REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    color_code TEXT DEFAULT '#800080',
    greeting TEXT DEFAULT 'Hi! how can I help you?',
    theme TEXT DEFAULT '#ffffff',
    logo_file_name TEXT
);

CREATE INDEX IF NOT EXISTS idx_chat_agents_workspace ON public."Chat_Agents"(workspace_id);
CREATE INDEX IF NOT EXISTS idx_chat_agents_profile ON public."Chat_Agents"(profile_id);

-- 4. Chat_Agent_history
CREATE TABLE IF NOT EXISTS public."Chat_Agent_history" (
    conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    profile_id UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    chat_agent_id UUID REFERENCES public."Chat_Agents"(id) ON DELETE CASCADE,
    conversation JSON[]
);

CREATE INDEX IF NOT EXISTS idx_chat_history_agent ON public."Chat_Agent_history"(chat_agent_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_profile ON public."Chat_Agent_history"(profile_id);
