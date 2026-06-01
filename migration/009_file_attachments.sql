-- ============================================================================
-- 009_file_attachments.sql
-- S3 file metadata table (replaces Supabase storage.buckets)
-- Tracks uploaded files with their S3 location
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.file_attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES public."Workspaces"(id) ON DELETE CASCADE,
    request_id UUID REFERENCES public.requests(id) ON DELETE SET NULL,
    chat_agent_id UUID REFERENCES public."Chat_Agents"(id) ON DELETE SET NULL,

    -- S3 location
    s3_bucket TEXT NOT NULL DEFAULT 'boa-application-data',
    s3_key TEXT NOT NULL,

    -- File metadata
    original_filename TEXT NOT NULL,
    file_size BIGINT,
    mime_type TEXT,

    -- Who uploaded
    uploaded_by UUID REFERENCES public.members(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_file_attachments_s3_key ON public.file_attachments(s3_bucket, s3_key);
CREATE INDEX IF NOT EXISTS idx_file_attachments_workspace ON public.file_attachments(workspace_id);
CREATE INDEX IF NOT EXISTS idx_file_attachments_request ON public.file_attachments(request_id) WHERE request_id IS NOT NULL;
