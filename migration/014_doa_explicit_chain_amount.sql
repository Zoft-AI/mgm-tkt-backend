-- ============================================================================
-- 014_doa_explicit_chain_amount.sql
-- Convert DOA rules to explicit_chain_amount type with department+unit chains.
-- Also update category from 'finance' to 'doa' for all DOA rules.
-- ============================================================================

-- 1. Update category for all 3 DOA rules
UPDATE public.rules SET category = 'doa'
WHERE id IN (
    'c7307199-db78-4c78-b3cb-1447465aafc5',  -- DOA CapEx
    '81029c5d-a4cb-45e9-82d1-203a297f7c24',  -- DOA CapEx - Add Budget
    'ac99c8d0-4847-440f-9291-aba7f668a30a'   -- Non-DOA CapEx
);

-- 2. Update "DOA CapEx" rule: change type to explicit_chain_amount with dept+unit chains
--    NOTE: Replace member_id placeholders (...) with actual member IDs from workspace 546edc6f-a4c0-4d74-a040-0a3003e675d4
UPDATE public.rules
SET
    rule_type = 'explicit_chain',
    data = '{
        "type": "explicit_chain_amount",
        "field": "amount",
        "sub_types": ["IT", "Finance", "Procurement", "HR", "Sales & Marketing"],
        "chains": {
            "IT": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Krishan", "member_id": "KRISHAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Venkat Rao", "member_id": "VENKAT_RAO_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sugumaran G", "member_id": "SUGUMARAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ramesh D", "member_id": "RAMESH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            },
            "Finance": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ganesh", "member_id": "GANESH_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ganesh", "member_id": "GANESH_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ganesh", "member_id": "GANESH_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - BrahmaJi", "member_id": "BRAHMAJI_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            },
            "Procurement": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Kesavan", "member_id": "KESAVAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sam", "member_id": "SAM_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ilamurugu", "member_id": "ILAMURUGU_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Bhuva Lakshmi", "member_id": "BHUVA_LAKSHMI_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            },
            "HR": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Salamath", "member_id": "SALAMATH_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Dr.Sujith", "member_id": "DR_SUJITH_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sekar V", "member_id": "SEKAR_V_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - BHANU CHEPPULA", "member_id": "BHANU_CHEPPULA_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            },
            "Sales & Marketing": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Senthilkumar A", "member_id": "SENTHILKUMAR_A_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Hemakumar", "member_id": "HEMAKUMAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Jayaprakash", "member_id": "JAYAPRAKASH_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sanjay", "member_id": "SANJAY_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 1000000},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 2500000},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 5000000},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            }
        },
        "currency": "INR",
        "sla_hours": 48,
        "products_source": "products_table",
        "required_fields": ["product_id", "quantity"]
    }'
WHERE id = 'c7307199-db78-4c78-b3cb-1447465aafc5';


-- 3. Update "DOA CapEx - Add Budget" rule: same structure but all max_amount: 0 (full chain)
--    Everyone must approve regardless of amount. max_amount: null on final (MD).
UPDATE public.rules
SET
    rule_type = 'explicit_chain',
    data = '{
        "type": "explicit_chain_amount",
        "field": "amount",
        "sub_types": ["IT", "Finance", "Procurement", "HR", "Sales & Marketing"],
        "chains": {
            "IT": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Krishan", "member_id": "KRISHAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Venkat Rao", "member_id": "VENKAT_RAO_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sugumaran G", "member_id": "SUGUMARAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ramesh D", "member_id": "RAMESH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 0},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            }
        },
        "currency": "INR",
        "sla_hours": 120,
        "description": "AOP CapEx Additional Budget: Full approval chain regardless of amount. Max 15% of original approved CapEx.",
        "max_limit_rule": "15% of original approved cap",
        "products_source": "products_table",
        "required_fields": ["product_id", "quantity"]
    }'
WHERE id = '81029c5d-a4cb-45e9-82d1-203a297f7c24';


-- 4. Update "Non-DOA CapEx" rule: same structure, full chain (all max_amount: 0)
UPDATE public.rules
SET
    rule_type = 'explicit_chain',
    data = '{
        "type": "explicit_chain_amount",
        "field": "amount",
        "sub_types": ["IT", "Finance", "Procurement", "HR", "Sales & Marketing"],
        "chains": {
            "IT": {
                "HC": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_HC_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Krishan", "member_id": "KRISHAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Nilesh M", "member_id": "NILESH_M_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "CI": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_CI_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Venkat Rao", "member_id": "VENKAT_RAO_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Saravanakumar", "member_id": "SARAVANAKUMAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "Malar": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_MALAR_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Sugumaran G", "member_id": "SUGUMARAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Venugopal", "member_id": "VENUGOPAL_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ],
                "SH": [
                    {"role": "Validation (Purchase)", "member_id": "PURCHASE_SH_MEMBER_ID", "max_amount": 0},
                    {"role": "Dept Head - Ramesh D", "member_id": "RAMESH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "Unit Head - Dr. Giri", "member_id": "DR_GIRI_MEMBER_ID", "max_amount": 0},
                    {"role": "Cluster Head - Pathmanaban SB", "member_id": "PATHMANABAN_MEMBER_ID", "max_amount": 0},
                    {"role": "Group CEO - Ilaiah D", "member_id": "ILAIAH_D_MEMBER_ID", "max_amount": 0},
                    {"role": "MD - Dr Prashanth", "member_id": "fc3dad09-cf16-470f-8489-265204b0861e", "max_amount": null}
                ]
            }
        },
        "currency": "INR",
        "sla_hours": 360,
        "description": "Non-AOP CapEx: Full approval chain for all amounts. Max 500L per year.",
        "max_limit_per_year": 50000000,
        "products_source": "products_table",
        "required_fields": ["product_id", "quantity"]
    }'
WHERE id = 'ac99c8d0-4847-440f-9291-aba7f668a30a';


-- ============================================================================
-- IMPORTANT: Before running this migration, replace ALL placeholder member_ids:
--
-- PURCHASE_HC_MEMBER_ID     = purchase@mgmhealthcare.in member ID
-- PURCHASE_CI_MEMBER_ID     = itsupport.mgmci@mgmcancerinstitute.in member ID (or purchase)
-- PURCHASE_MALAR_MEMBER_ID  = itsupport.mgmmalar@mgmhcmalar.in member ID (or purchase)
-- PURCHASE_SH_MEMBER_ID     = it@mgmsevenhills.in member ID (or purchase)
-- KRISHAN_MEMBER_ID         = Krishan (IT Dept Head, HC)
-- GANESH_HC_MEMBER_ID       = Ganesh (Finance Dept Head, HC)
-- GANESH_CI_MEMBER_ID       = Ganesh (Finance Dept Head, CI)
-- GANESH_MALAR_MEMBER_ID    = Ganesh (Finance Dept Head, Malar)
-- KESAVAN_MEMBER_ID         = Kesavan (Procurement Dept Head, HC)
-- SALAMATH_MEMBER_ID        = Salamath (HR Dept Head, HC)
-- SENTHILKUMAR_A_MEMBER_ID  = Senthilkumar A (Sales & Marketing Dept Head, HC)
-- VENKAT_RAO_MEMBER_ID      = Venkat Rao (IT Dept Head, CI)
-- SAM_MEMBER_ID             = Sam (Procurement Dept Head, CI)
-- DR_SUJITH_MEMBER_ID       = Dr.Sujith (HR Dept Head, CI)
-- HEMAKUMAR_MEMBER_ID       = Hemakumar (Sales & Marketing Dept Head, CI)
-- SUGUMARAN_MEMBER_ID       = Sugumaran G (IT Dept Head, Malar)
-- ILAMURUGU_MEMBER_ID       = Ilamurugu (Procurement Dept Head, Malar)
-- SEKAR_V_MEMBER_ID         = Sekar V (HR Dept Head, Malar)
-- JAYAPRAKASH_MEMBER_ID     = Jayaprakash (Sales & Marketing Dept Head, Malar)
-- RAMESH_D_MEMBER_ID        = Ramesh D (IT Dept Head, SH)
-- BRAHMAJI_MEMBER_ID        = BrahmaJi (Finance Dept Head, SH)
-- BHUVA_LAKSHMI_MEMBER_ID   = Bhuva Lakshmi (Procurement Dept Head, SH)
-- BHANU_CHEPPULA_MEMBER_ID  = BHANU CHEPPULA (HR Dept Head, SH)
-- SANJAY_MEMBER_ID          = Sanjay (Sales & Marketing Dept Head, SH)
-- NILESH_M_MEMBER_ID        = Nilesh M (Unit Head, HC)
-- SARAVANAKUMAR_MEMBER_ID   = Saravanakumar (Unit Head, CI)
-- VENUGOPAL_MEMBER_ID       = Venugopal (Unit Head, Malar)
-- DR_GIRI_MEMBER_ID         = Dr. Giri (Unit Head, SH)
-- PATHMANABAN_MEMBER_ID     = Pathmanaban SB (Cluster Head, CI & SH)
-- ILAIAH_D_MEMBER_ID        = Ilaiah D (Group CEO)
--
-- NOTE: For "Add Budget" and "Non-DOA", only IT department chains are shown as example.
-- You should add all 5 departments (same people as DOA CapEx) for these rules too.
-- ============================================================================
