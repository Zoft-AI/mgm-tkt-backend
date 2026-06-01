-- ============================================================================
-- 016_auth_refresh_tokens.sql
-- Refresh token storage for JWT rotation
-- Each token is stored as a SHA-256 hash for security
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.auth_refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked BOOLEAN DEFAULT false,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    user_agent TEXT,
    ip_address TEXT
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON public.auth_refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON public.auth_refresh_tokens(token_hash) WHERE revoked = false;
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires ON public.auth_refresh_tokens(expires_at) WHERE revoked = false;
