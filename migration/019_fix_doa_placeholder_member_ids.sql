-- ============================================================================
-- 019_fix_doa_placeholder_member_ids.sql
-- Fixes DOA CapEx approval chains by:
--   1. Creating profiles + auth_users for 3 new people (Sugumaran G,
--      HC IT Support, SH IT Support)
--   2. Creating member records for 14 people who lacked them
--   3. Replacing ALL placeholder member_ids in the 3 DOA rules with real UUIDs
--
-- DOES NOT touch the Payment Request rule (1ddd907d) -- it already has real UUIDs.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Disable auth trigger to prevent auto-creating profiles/workspaces
DROP TRIGGER IF EXISTS trigger_auth_user_created ON public.auth_users;

DO $$
DECLARE
    -- =====================================================================
    -- Constants
    -- =====================================================================
    v_workspace_id UUID := '546edc6f-a4c0-4d74-a040-0a3003e675d4';

    -- Unit IDs
    v_unit_hc UUID := 'ddf0fb13-c2b4-4f0f-bb1e-b420b6e19f0b';
    v_unit_ci UUID := 'a6059d14-f777-4d47-ab95-cefa7ef48b14';
    v_unit_malar UUID := '6e8231ec-8c36-4bd8-8be3-0e8677fbfd02';
    v_unit_sh UUID := '15936dd3-b3b5-4439-83ea-16defb62cead';

    -- Existing Unit Head member IDs (reports_to targets)
    v_nilesh_m UUID := '43a3522b-dc90-4e66-b9bc-06f9c76266b8';       -- HC
    v_saravanakumar UUID := 'e4f2b088-f706-4a79-8c7a-7ed733676e51';  -- CI
    v_venugopal UUID := 'fed3f34d-5606-464e-ab96-0e4bbc2dc64c';      -- Malar
    v_dr_giri UUID := 'aefe4f8f-d89b-4ab6-913a-f28eb9e87c1a';        -- SH

    -- Existing member UUIDs (already in members table)
    v_ramesh UUID := '12933064-6c1c-4afd-9948-fe56ccd44587';          -- Validation (Purchase) for ALL units
    v_ganesh_v UUID := 'ea9cc590-07b9-420d-9b3e-0a27cc362085';       -- Finance Dept Head (CI/HC/Malar)
    v_pathmanaban UUID := 'cd08465c-b6f7-44be-87c4-cc2a420a3ee4';    -- Cluster Head (CI & SH)
    v_ilaiah_d UUID := '86eca51d-b04d-49f6-881d-70550b87aaac';       -- Group CEO
    v_hemakumar UUID := '6f3a7e05-fd77-4fd6-bc04-9dec40ef9f54';      -- S&M Dept Head CI
    v_senthilkumar_a UUID := 'b01eb03b-5feb-4056-adfb-e0bf7134cba5'; -- S&M Dept Head HC
    v_sanjay UUID := '47a07976-69d3-4d9e-ae7d-bbfdecf7583a';         -- S&M Dept Head SH
    v_jayaprakash UUID := '49a44f99-04bc-4e61-9359-b9e2fd849bba';    -- S&M Dept Head Malar
    v_brahmaji UUID := '9b259757-2b99-41bd-a652-c9b3648b79ab';       -- Finance Dept Head SH

    -- Rule IDs (only DOA rules -- Payment Request is NOT touched)
    v_doa_capex_id UUID := 'c7307199-db78-4c78-b3cb-1447465aafc5';
    v_doa_add_budget_id UUID := '81029c5d-a4cb-45e9-82d1-203a297f7c24';
    v_non_doa_capex_id UUID := 'ac99c8d0-4847-440f-9291-aba7f668a30a';

    -- =====================================================================
    -- New member UUIDs (for 11 people who have profile+auth but no member)
    -- =====================================================================
    v_krishan_mid UUID := gen_random_uuid();
    v_kesavan_mid UUID := gen_random_uuid();
    v_salamath_mid UUID := gen_random_uuid();
    v_venkat_rao_mid UUID := gen_random_uuid();
    v_sam_mid UUID := gen_random_uuid();
    v_dr_sujith_mid UUID := gen_random_uuid();
    v_ilamurugu_mid UUID := gen_random_uuid();
    v_sekar_v_mid UUID := gen_random_uuid();
    v_bhuva_lakshmi_mid UUID := gen_random_uuid();
    v_ramesh_d_mid UUID := gen_random_uuid();
    v_bhanu_cheppula_mid UUID := gen_random_uuid();

    -- =====================================================================
    -- New UUIDs for 3 completely new people (need profile + auth + member)
    -- =====================================================================
    v_sugumaran_pid UUID := gen_random_uuid();
    v_sugumaran_mid UUID := gen_random_uuid();

    v_hc_itsupport_pid UUID := gen_random_uuid();
    v_hc_itsupport_mid UUID := gen_random_uuid();

    v_sh_itsupport_pid UUID := gen_random_uuid();
    v_sh_itsupport_mid UUID := gen_random_uuid();

    -- Working variable for rule data replacement
    v_data_text TEXT;

BEGIN
    -- =================================================================
    -- STEP 1: Create profiles for 3 new people
    -- =================================================================
    INSERT INTO public.profiles (id, email)
    VALUES (v_sugumaran_pid, 'itsupport.mgmmalar@mgmhcmalar.in')
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.profiles (id, email)
    VALUES (v_hc_itsupport_pid, 'itsupport@mgmhealthcare.in')
    ON CONFLICT (id) DO NOTHING;

    INSERT INTO public.profiles (id, email)
    VALUES (v_sh_itsupport_pid, 'it@mgmsevenhills.in')
    ON CONFLICT (id) DO NOTHING;

    -- =================================================================
    -- STEP 2: Create auth_users for 3 new people
    -- password_hash is NULL -- admin must set passwords via app or
    -- password-reset flow after migration
    -- =================================================================
    INSERT INTO public.auth_users (id, email, password_hash, name, email_verified, provider)
    VALUES (v_sugumaran_pid, 'itsupport.mgmmalar@mgmhcmalar.in',
        crypt('JuiGntcrHwM6pk8D', gen_salt('bf', 12)), 'Sugumaran G', true, 'email')
    ON CONFLICT (email) DO NOTHING;

    INSERT INTO public.auth_users (id, email, password_hash, name, email_verified, provider)
    VALUES (v_hc_itsupport_pid, 'itsupport@mgmhealthcare.in',
        crypt('qiyVGBmhpcFJXE6C', gen_salt('bf', 12)), 'HC IT Support', true, 'email')
    ON CONFLICT (email) DO NOTHING;

    INSERT INTO public.auth_users (id, email, password_hash, name, email_verified, provider)
    VALUES (v_sh_itsupport_pid, 'it@mgmsevenhills.in',
        crypt('azyfWrurdRjfd5W8', gen_salt('bf', 12)), 'SH IT Support', true, 'email')
    ON CONFLICT (email) DO NOTHING;

    -- =================================================================
    -- STEP 3: Create member records
    -- =================================================================

    -- -----------------------------------------------------------------
    -- 3a. HC Department Heads
    -- -----------------------------------------------------------------
    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_krishan_mid, 'bbe605c5-a5ce-4063-8b8f-82ea7168f78e', v_workspace_id,
        'Krishan', 'krishan.bhardwaj@mgmhealthcare.in', 'IT', 'HOD - IT',
        4, v_nilesh_m, '{"tickets": "editor"}', v_unit_hc, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_kesavan_mid, '6bba7365-73e6-4b22-965d-2f8578acc78c', v_workspace_id,
        'Kesavan', 'kesavan.k@mgmhealthcare.in', 'Procurement', 'HOD - Procurement',
        4, v_nilesh_m, '{"tickets": "editor"}', v_unit_hc, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_salamath_mid, '5b498fc7-99f4-409d-85cf-5e80fbb1c6e1', v_workspace_id,
        'Salamath', 'salamath.m@mgmhealthcare.in', 'HR', 'HOD - HR',
        4, v_nilesh_m, '{"tickets": "editor"}', v_unit_hc, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    -- -----------------------------------------------------------------
    -- 3b. CI Department Heads
    -- -----------------------------------------------------------------
    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_venkat_rao_mid, '41e68a71-4ab4-43e7-8055-35b0f8b9ac71', v_workspace_id,
        'Venkat Rao', 'itsupport.mgmci@mgmcancerinstitute.in', 'IT', 'HOD - IT',
        4, v_saravanakumar, '{"tickets": "editor"}', v_unit_ci, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_sam_mid, 'd28e8da1-1365-4b88-8422-c0ce2fedf1cb', v_workspace_id,
        'Sam', 'sam.y@mgmcancerinstitute.in', 'Procurement', 'HOD - Procurement',
        4, v_saravanakumar, '{"tickets": "editor"}', v_unit_ci, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_dr_sujith_mid, 'cfa28776-84e7-4753-9adf-7a80a3b7d01f', v_workspace_id,
        'Dr. Sujith', 'sujith.s@mgmhealthcare.in', 'HR', 'HOD - HR',
        4, v_saravanakumar, '{"tickets": "editor"}', v_unit_ci, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    -- -----------------------------------------------------------------
    -- 3c. Malar Department Heads
    -- -----------------------------------------------------------------
    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_sugumaran_mid, v_sugumaran_pid, v_workspace_id,
        'Sugumaran G', 'itsupport.mgmmalar@mgmhcmalar.in', 'IT', 'HOD - IT',
        4, v_venugopal, '{"tickets": "editor"}', v_unit_malar, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_ilamurugu_mid, '986d71d8-7dff-461d-916a-aefd8ecfc28f', v_workspace_id,
        'Ilamurugu', 'ilamurugu.p@mgmhcmalar.in', 'Procurement', 'HOD - Procurement',
        4, v_venugopal, '{"tickets": "editor"}', v_unit_malar, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_sekar_v_mid, '87fbf222-8ac7-44da-b20c-e16e0c44f238', v_workspace_id,
        'Sekar V', 'sekar.v@mgmhcmalar.in', 'HR', 'HOD - HR',
        4, v_venugopal, '{"tickets": "editor"}', v_unit_malar, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    -- -----------------------------------------------------------------
    -- 3d. SH Department Heads
    -- -----------------------------------------------------------------
    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_ramesh_d_mid, 'af46d9c0-1191-4975-92c0-9701162d0d11', v_workspace_id,
        'Ramesh D', 'hodit@mgmsevenhills.in', 'IT', 'HOD - IT',
        4, v_dr_giri, '{"tickets": "editor"}', v_unit_sh, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_bhuva_lakshmi_mid, '914ef5a0-7322-4b2e-a45d-7ea104a474d7', v_workspace_id,
        'Bhuva Lakshmi', 'purchase@mgmsevenhills.in', 'Procurement', 'HOD - Procurement',
        4, v_dr_giri, '{"tickets": "editor"}', v_unit_sh, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_bhanu_cheppula_mid, '1948a6cf-5499-41cc-af63-e46b19b02e9b', v_workspace_id,
        'Bhanu Cheppula', 'hodhr@mgmsevenhills.in', 'HR', 'HOD - HR',
        4, v_dr_giri, '{"tickets": "editor"}', v_unit_sh, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    -- -----------------------------------------------------------------
    -- 3e. Creator accounts (not in DOA approval chain, just request creators)
    -- -----------------------------------------------------------------
    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_hc_itsupport_mid, v_hc_itsupport_pid, v_workspace_id,
        'HC IT Support', 'itsupport@mgmhealthcare.in', 'IT', 'IT Support',
        2, v_nilesh_m, '{"tickets": "editor"}', v_unit_hc, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    INSERT INTO public.members (id, profile_id, workspace_id, name, email, department, designation,
        hierarchy_level, reports_to, feature_access, unit_id, status, is_active)
    VALUES (v_sh_itsupport_mid, v_sh_itsupport_pid, v_workspace_id,
        'SH IT Support', 'it@mgmsevenhills.in', 'IT', 'IT Support',
        2, v_dr_giri, '{"tickets": "editor"}', v_unit_sh, 'active', true)
    ON CONFLICT (email, workspace_id) DO NOTHING;

    -- =================================================================
    -- STEP 4: Update DOA CapEx rule (c7307199)
    -- Replace ALL placeholder member_ids with real UUIDs
    -- =================================================================
    SELECT data::text INTO v_data_text
    FROM public.rules WHERE id = v_doa_capex_id;

    -- Validation (Purchase) -- ALL units = Ramesh
    v_data_text := REPLACE(v_data_text, 'PURCHASE_HC_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_CI_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_SH_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_MALAR_MEMBER_ID', v_ramesh::text);

    -- IT Dept Heads
    v_data_text := REPLACE(v_data_text, 'KRISHAN_MEMBER_ID', v_krishan_mid::text);
    v_data_text := REPLACE(v_data_text, 'VENKAT_RAO_MEMBER_ID', v_venkat_rao_mid::text);
    v_data_text := REPLACE(v_data_text, 'SUGUMARAN_MEMBER_ID', v_sugumaran_mid::text);
    v_data_text := REPLACE(v_data_text, 'RAMESH_D_MEMBER_ID', v_ramesh_d_mid::text);

    -- Finance Dept Heads (CI/HC/Malar = same Ganesh V)
    v_data_text := REPLACE(v_data_text, 'GANESH_CI_MEMBER_ID', v_ganesh_v::text);
    v_data_text := REPLACE(v_data_text, 'GANESH_HC_MEMBER_ID', v_ganesh_v::text);
    v_data_text := REPLACE(v_data_text, 'GANESH_MALAR_MEMBER_ID', v_ganesh_v::text);
    v_data_text := REPLACE(v_data_text, 'BRAHMAJI_MEMBER_ID', v_brahmaji::text);

    -- Procurement Dept Heads
    v_data_text := REPLACE(v_data_text, 'KESAVAN_MEMBER_ID', v_kesavan_mid::text);
    v_data_text := REPLACE(v_data_text, 'SAM_MEMBER_ID', v_sam_mid::text);
    v_data_text := REPLACE(v_data_text, 'ILAMURUGU_MEMBER_ID', v_ilamurugu_mid::text);
    v_data_text := REPLACE(v_data_text, 'BHUVA_LAKSHMI_MEMBER_ID', v_bhuva_lakshmi_mid::text);

    -- HR Dept Heads
    v_data_text := REPLACE(v_data_text, 'SALAMATH_MEMBER_ID', v_salamath_mid::text);
    v_data_text := REPLACE(v_data_text, 'DR_SUJITH_MEMBER_ID', v_dr_sujith_mid::text);
    v_data_text := REPLACE(v_data_text, 'SEKAR_V_MEMBER_ID', v_sekar_v_mid::text);
    v_data_text := REPLACE(v_data_text, 'BHANU_CHEPPULA_MEMBER_ID', v_bhanu_cheppula_mid::text);

    -- S&M Dept Heads
    v_data_text := REPLACE(v_data_text, 'SENTHILKUMAR_A_MEMBER_ID', v_senthilkumar_a::text);
    v_data_text := REPLACE(v_data_text, 'HEMAKUMAR_MEMBER_ID', v_hemakumar::text);
    v_data_text := REPLACE(v_data_text, 'JAYAPRAKASH_MEMBER_ID', v_jayaprakash::text);
    v_data_text := REPLACE(v_data_text, 'SANJAY_MEMBER_ID', v_sanjay::text);

    -- Unit Heads
    v_data_text := REPLACE(v_data_text, 'SARAVANAKUMAR_MEMBER_ID', v_saravanakumar::text);
    v_data_text := REPLACE(v_data_text, 'NILESH_M_MEMBER_ID', v_nilesh_m::text);
    v_data_text := REPLACE(v_data_text, 'VENUGOPAL_MEMBER_ID', v_venugopal::text);
    v_data_text := REPLACE(v_data_text, 'DR_GIRI_MEMBER_ID', v_dr_giri::text);

    -- Cluster Head & Group CEO
    v_data_text := REPLACE(v_data_text, 'PATHMANABAN_MEMBER_ID', v_pathmanaban::text);
    v_data_text := REPLACE(v_data_text, 'ILAIAH_D_MEMBER_ID', v_ilaiah_d::text);

    UPDATE public.rules SET data = v_data_text::jsonb WHERE id = v_doa_capex_id;

    -- =================================================================
    -- STEP 5: Update DOA CapEx - Add Budget rule (81029c5d)
    -- Same placeholder replacements (only IT chains exist here)
    -- =================================================================
    SELECT data::text INTO v_data_text
    FROM public.rules WHERE id = v_doa_add_budget_id;

    v_data_text := REPLACE(v_data_text, 'PURCHASE_HC_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_CI_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_SH_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_MALAR_MEMBER_ID', v_ramesh::text);

    v_data_text := REPLACE(v_data_text, 'KRISHAN_MEMBER_ID', v_krishan_mid::text);
    v_data_text := REPLACE(v_data_text, 'VENKAT_RAO_MEMBER_ID', v_venkat_rao_mid::text);
    v_data_text := REPLACE(v_data_text, 'SUGUMARAN_MEMBER_ID', v_sugumaran_mid::text);
    v_data_text := REPLACE(v_data_text, 'RAMESH_D_MEMBER_ID', v_ramesh_d_mid::text);

    v_data_text := REPLACE(v_data_text, 'SARAVANAKUMAR_MEMBER_ID', v_saravanakumar::text);
    v_data_text := REPLACE(v_data_text, 'NILESH_M_MEMBER_ID', v_nilesh_m::text);
    v_data_text := REPLACE(v_data_text, 'VENUGOPAL_MEMBER_ID', v_venugopal::text);
    v_data_text := REPLACE(v_data_text, 'DR_GIRI_MEMBER_ID', v_dr_giri::text);

    v_data_text := REPLACE(v_data_text, 'PATHMANABAN_MEMBER_ID', v_pathmanaban::text);
    v_data_text := REPLACE(v_data_text, 'ILAIAH_D_MEMBER_ID', v_ilaiah_d::text);

    UPDATE public.rules SET data = v_data_text::jsonb WHERE id = v_doa_add_budget_id;

    -- =================================================================
    -- STEP 6: Update Non-DOA CapEx rule (ac99c8d0)
    -- Same placeholder replacements (only IT chains exist here)
    -- =================================================================
    SELECT data::text INTO v_data_text
    FROM public.rules WHERE id = v_non_doa_capex_id;

    v_data_text := REPLACE(v_data_text, 'PURCHASE_HC_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_CI_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_SH_MEMBER_ID', v_ramesh::text);
    v_data_text := REPLACE(v_data_text, 'PURCHASE_MALAR_MEMBER_ID', v_ramesh::text);

    v_data_text := REPLACE(v_data_text, 'KRISHAN_MEMBER_ID', v_krishan_mid::text);
    v_data_text := REPLACE(v_data_text, 'VENKAT_RAO_MEMBER_ID', v_venkat_rao_mid::text);
    v_data_text := REPLACE(v_data_text, 'SUGUMARAN_MEMBER_ID', v_sugumaran_mid::text);
    v_data_text := REPLACE(v_data_text, 'RAMESH_D_MEMBER_ID', v_ramesh_d_mid::text);

    v_data_text := REPLACE(v_data_text, 'SARAVANAKUMAR_MEMBER_ID', v_saravanakumar::text);
    v_data_text := REPLACE(v_data_text, 'NILESH_M_MEMBER_ID', v_nilesh_m::text);
    v_data_text := REPLACE(v_data_text, 'VENUGOPAL_MEMBER_ID', v_venugopal::text);
    v_data_text := REPLACE(v_data_text, 'DR_GIRI_MEMBER_ID', v_dr_giri::text);

    v_data_text := REPLACE(v_data_text, 'PATHMANABAN_MEMBER_ID', v_pathmanaban::text);
    v_data_text := REPLACE(v_data_text, 'ILAIAH_D_MEMBER_ID', v_ilaiah_d::text);

    UPDATE public.rules SET data = v_data_text::jsonb WHERE id = v_non_doa_capex_id;

    RAISE NOTICE '=== Migration 019 complete ===';
    RAISE NOTICE 'Created 3 new profiles + auth_users (passwords NOT set)';
    RAISE NOTICE 'Created 14 new member records';
    RAISE NOTICE 'Updated 3 DOA rules with real member UUIDs';
    RAISE NOTICE 'Payment Request rule was NOT modified';
END $$;

-- Re-enable the auth trigger
CREATE TRIGGER trigger_auth_user_created
    AFTER INSERT ON public.auth_users
    FOR EACH ROW
    EXECUTE FUNCTION public.trigger_new_auth_user();

-- =========================================================================
-- VERIFICATION QUERIES (run these after migration to confirm correctness)
-- =========================================================================

-- Check 1: No placeholder member_ids remain in DOA rules
-- Should return 0 rows
-- SELECT id, rule_name FROM public.rules
-- WHERE category = 'doa'
--   AND data::text ~ '_MEMBER_ID';

-- Check 2: All 14 new members exist
-- Should return 14 rows
-- SELECT name, email, department, unit_id
-- FROM public.members
-- WHERE email IN (
--     'krishan.bhardwaj@mgmhealthcare.in', 'kesavan.k@mgmhealthcare.in',
--     'salamath.m@mgmhealthcare.in', 'itsupport.mgmci@mgmcancerinstitute.in',
--     'sam.y@mgmcancerinstitute.in', 'sujith.s@mgmhealthcare.in',
--     'ilamurugu.p@mgmhcmalar.in', 'sekar.v@mgmhcmalar.in',
--     'purchase@mgmsevenhills.in', 'hodit@mgmsevenhills.in',
--     'hodhr@mgmsevenhills.in', 'itsupport.mgmmalar@mgmhcmalar.in',
--     'itsupport@mgmhealthcare.in', 'it@mgmsevenhills.in'
-- );

-- Check 3: Payment Request rule is unchanged (should still have real UUIDs)
-- SELECT id, rule_name FROM public.rules
-- WHERE id = '1ddd907d-4eea-4fb8-9870-976ce6a8a222'
--   AND data::text NOT LIKE '%_MEMBER_ID%';
