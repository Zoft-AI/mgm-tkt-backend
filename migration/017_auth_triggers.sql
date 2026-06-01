-- ============================================================================
-- 017_auth_triggers.sql
-- Trigger: when a new auth_users row is inserted, auto-create profile + workspace
-- Also: cleanup function for expired/revoked refresh tokens
-- ============================================================================

-- When a new user signs up, create their profile + default workspace + owner member
CREATE OR REPLACE FUNCTION public.trigger_new_auth_user()
RETURNS TRIGGER AS $$
BEGIN
    PERFORM create_new_user(NEW.id, NEW.email, NEW.name);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_auth_user_created ON public.auth_users;

CREATE TRIGGER trigger_auth_user_created
    AFTER INSERT ON public.auth_users
    FOR EACH ROW
    EXECUTE FUNCTION public.trigger_new_auth_user();

-- Cleanup expired/revoked refresh tokens (call via cron or scheduled task)
CREATE OR REPLACE FUNCTION public.cleanup_expired_tokens()
RETURNS void AS $$
BEGIN
    DELETE FROM public.auth_refresh_tokens
    WHERE expires_at < NOW()
       OR (revoked = true AND revoked_at < NOW() - INTERVAL '7 days');
END;
$$ LANGUAGE plpgsql;
