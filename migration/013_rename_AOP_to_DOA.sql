-- ============================================================================
-- 013_rename_AOP_to_DOA.sql
-- Rename "AOP" rules to "DOA" in the rules table.
-- ============================================================================

UPDATE public.rules SET rule_name = 'DOA CapEx'
WHERE id = 'c7307199-db78-4c78-b3cb-1447465aafc5';

UPDATE public.rules SET rule_name = 'DOA CapEx - Add Budget'
WHERE id = '81029c5d-a4cb-45e9-82d1-203a297f7c24';

UPDATE public.rules SET rule_name = 'Non-DOA CapEx'
WHERE id = 'ac99c8d0-4847-440f-9291-aba7f668a30a';
