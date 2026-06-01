-- ============================================================================
-- 015_auth_users.sql
-- Custom authentication table (replaces Supabase auth.users)
-- Stores user credentials, email verification, and OAuth provider data
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.auth_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,
    name TEXT,
    email_verified BOOLEAN DEFAULT false,
    email_verify_token TEXT,
    email_verify_expires_at TIMESTAMPTZ,
    password_reset_token TEXT,
    password_reset_expires_at TIMESTAMPTZ,
    provider TEXT DEFAULT 'email',
    provider_user_id TEXT,
    provider_data JSONB DEFAULT '{}',
    last_sign_in_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_auth_users_email ON public.auth_users(email);
CREATE INDEX IF NOT EXISTS idx_auth_users_verify_token ON public.auth_users(email_verify_token) WHERE email_verify_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_users_reset_token ON public.auth_users(password_reset_token) WHERE password_reset_token IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_users_provider ON public.auth_users(provider, provider_user_id) WHERE provider != 'email';

-- updated_at trigger
CREATE OR REPLACE FUNCTION public.update_auth_users_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_auth_users_updated_at
    BEFORE UPDATE ON public.auth_users
    FOR EACH ROW
    EXECUTE FUNCTION public.update_auth_users_updated_at();
