-- ============================================================================
-- 010_functions.sql
-- All database functions: signup, profile linking, request RPCs, health check
-- Sources: AI_crud migrations 006, 012, 013, 025
-- ============================================================================

-- ============================================================================
-- 1. create_new_user() - Callable function for signup flow
--    On Supabase: called via RPC after auth signup
--    On RDS: called by Python auth service directly
--    Creates profile + workspace + owner member, or activates pending invite
-- ============================================================================
CREATE OR REPLACE FUNCTION public.create_new_user(
    p_user_id UUID,
    p_email TEXT,
    p_name TEXT DEFAULT NULL
)
RETURNS VOID
LANGUAGE plpgsql
AS $$
DECLARE
    v_email        TEXT;
    v_name         TEXT;
    v_workspace_id UUID;
    v_has_invite   BOOLEAN;
BEGIN
    v_email := lower(coalesce(p_email, ''));
    v_name  := coalesce(
        nullif(trim(p_name), ''),
        split_part(v_email, '@', 1)
    );

    -- 1. Create profile
    INSERT INTO public.profiles (id, email)
    VALUES (p_user_id, v_email)
    ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email;

    -- 2. Check for pending invites
    SELECT EXISTS (
        SELECT 1 FROM public.members
        WHERE email = v_email
          AND profile_id IS NULL
          AND status = 'pending'
    ) INTO v_has_invite;

    IF v_has_invite THEN
        -- Activate all pending invites + clear invitation token
        UPDATE public.members
        SET
            profile_id            = p_user_id,
            status                = 'active',
            invitation_token      = NULL,
            invitation_expires_at = NULL,
            name                  = COALESCE(members.name, v_name),
            updated_at            = NOW()
        WHERE
            email = v_email
            AND profile_id IS NULL
            AND status = 'pending';
    ELSE
        -- 3. No invite -> create default workspace + owner member
        INSERT INTO public."Workspaces" (profile_id, workspace_name)
        VALUES (p_user_id, 'Untitled')
        RETURNING id INTO v_workspace_id;

        INSERT INTO public.members (
            workspace_id, profile_id, email, name,
            hierarchy_level, designation, status,
            is_owner, is_active, data
        )
        VALUES (
            v_workspace_id, p_user_id, v_email, v_name,
            6, 'Owner', 'active',
            true, true,
            jsonb_build_object('auto_created', true, 'source', 'auth_signup')
        );
    END IF;
END;
$$;

-- ============================================================================
-- 2. link_member_profile() - Auto-link pending members when profile is created
--    Source: AI_crud migration 006
-- ============================================================================
CREATE OR REPLACE FUNCTION public.link_member_profile()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE public.members
    SET
        profile_id = NEW.id,
        status = 'active',
        updated_at = NOW()
    WHERE
        email = NEW.email
        AND profile_id IS NULL
        AND status = 'pending';

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_link_member_profile ON public.profiles;

CREATE TRIGGER trigger_link_member_profile
AFTER INSERT ON public.profiles
FOR EACH ROW
EXECUTE FUNCTION public.link_member_profile();

-- ============================================================================
-- 3. get_requests_approved_by_member() - Requests acted on by a member
--    Source: AI_crud migration 012
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_requests_approved_by_member(
    p_agent_id UUID,
    p_member_id UUID,
    p_limit INT DEFAULT 20,
    p_offset INT DEFAULT 0
)
RETURNS SETOF public.requests
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT r.*
    FROM public.requests r
    WHERE r.chat_agent_id = p_agent_id
    AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(r.history, '[]'::jsonb)) AS elem
        WHERE elem->>'by_id' = p_member_id::text
          AND elem->>'action' IN ('approved', 'rejected')
    )
    ORDER BY r.updated_at DESC
    LIMIT p_limit
    OFFSET p_offset;
END;
$$;

-- ============================================================================
-- 4. get_requests_approved_by_member_count() - Count for pagination
--    Source: AI_crud migration 012
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_requests_approved_by_member_count(
    p_agent_id UUID,
    p_member_id UUID
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_count BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_count
    FROM public.requests r
    WHERE r.chat_agent_id = p_agent_id
    AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(r.history, '[]'::jsonb)) AS elem
        WHERE elem->>'by_id' = p_member_id::text
          AND elem->>'action' IN ('approved', 'rejected')
    );
    RETURN v_count;
END;
$$;

-- ============================================================================
-- 5. get_my_approval_stats() - Dashboard stats (pending/approved/rejected)
--    Source: AI_crud migration 013
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_my_approval_stats(
    p_agent_id UUID,
    p_member_id UUID
)
RETURNS JSONB
LANGUAGE plpgsql
AS $$
DECLARE
    v_pending BIGINT;
    v_approved BIGINT;
    v_rejected BIGINT;
BEGIN
    SELECT COUNT(*) INTO v_pending
    FROM public.requests r
    WHERE r.chat_agent_id = p_agent_id
      AND r.current_approver = p_member_id
      AND r.status = 'pending';

    SELECT COUNT(*) INTO v_approved
    FROM public.requests r
    WHERE r.chat_agent_id = p_agent_id
    AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(r.history, '[]'::jsonb)) AS elem
        WHERE elem->>'by_id' = p_member_id::text AND elem->>'action' = 'approved'
    );

    SELECT COUNT(*) INTO v_rejected
    FROM public.requests r
    WHERE r.chat_agent_id = p_agent_id
    AND EXISTS (
        SELECT 1 FROM jsonb_array_elements(COALESCE(r.history, '[]'::jsonb)) AS elem
        WHERE elem->>'by_id' = p_member_id::text AND elem->>'action' = 'rejected'
    );

    RETURN jsonb_build_object(
        'total', v_pending + v_approved + v_rejected,
        'pending', v_pending,
        'approved', v_approved,
        'rejected', v_rejected
    );
END;
$$;

-- ============================================================================
-- 6. get_service_status() - Simple health check
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_service_status()
RETURNS TEXT
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN 'ok';
END;
$$;
