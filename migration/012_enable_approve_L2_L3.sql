-- ============================================================================
-- 012_enable_approve_L2_L3.sql
-- Enable can_approve for Level 2 (Procurement) and Level 3 (Proc Head).
-- Previously these levels had can_approve=false + receives_only=true,
-- meaning they were skipped during approval chain building.
-- ============================================================================

-- L2: Procurement — enable approval, remove receives_only, grant approve permission
UPDATE public.hierarchy
SET data = jsonb_set(
            jsonb_set(
              data - 'receives_only',
              '{can_approve}', 'true'
            ),
            '{permissions}', '["view", "create", "approve"]'
          )
WHERE workspace_id = '546edc6f-a4c0-4d74-a040-0a3003e675d4'
  AND level = 2;

-- L3: Proc Head — enable approval, remove receives_only, grant approve permission
UPDATE public.hierarchy
SET data = jsonb_set(
            jsonb_set(
              data - 'receives_only',
              '{can_approve}', 'true'
            ),
            '{permissions}', '["view", "create", "approve"]'
          )
WHERE workspace_id = '546edc6f-a4c0-4d74-a040-0a3003e675d4'
  AND level = 3;
