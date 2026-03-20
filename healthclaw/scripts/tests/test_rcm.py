"""Tests for HealthClaw RCM domain (payer registry + eligibility verification).

Actions tested (payer):
  - health-add-payer
  - health-update-payer
  - health-get-payer
  - health-list-payers
  - health-link-payer-fee-schedule
  - health-payer-performance-report
Actions tested (eligibility):
  - health-record-eligibility-check
  - health-get-latest-eligibility
  - health-list-eligibility-checks
  - health-check-eligibility-status
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_payer(conn, env, name="Aetna Commercial", payer_type="commercial", **kwargs):
    """Create a payer and return the result dict."""
    return call_action(mod.health_add_payer, conn, ns(
        company_id=env["company_id"],
        name=name,
        payer_type=payer_type,
        edi_payer_id=kwargs.get("edi_payer_id"),
        electronic_filing_id=kwargs.get("electronic_filing_id"),
        address=kwargs.get("address"),
        city=kwargs.get("city"),
        state=kwargs.get("state"),
        zip_code=kwargs.get("zip_code"),
        phone=kwargs.get("phone"),
        claims_address=kwargs.get("claims_address"),
        claims_city=kwargs.get("claims_city"),
        claims_state=kwargs.get("claims_state"),
        claims_zip=kwargs.get("claims_zip"),
        submission_method=kwargs.get("submission_method"),
        timely_filing_days=kwargs.get("timely_filing_days"),
        era_enrollment=kwargs.get("era_enrollment"),
        notes=kwargs.get("notes"),
        limit=50, offset=0,
    ))


def _add_insurance(conn, env, payer_name="TestPayer", member_id="MEM-001"):
    """Create patient insurance and return the result dict."""
    return call_action(mod.health_add_patient_insurance, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        insurance_type="primary",
        payer_name=payer_name,
        payer_id=None, plan_name=None, plan_type=None,
        group_number=None, member_id=member_id,
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None,
        copay_amount=None, deductible=None, deductible_met=None,
        out_of_pocket_max=None, effective_date="2026-01-01",
        termination_date=None, preauth_required=None, status=None,
        limit=50, offset=0,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# Payer Registry
# ─────────────────────────────────────────────────────────────────────────────

class TestPayer:
    def test_add_payer_happy_path(self, conn, env):
        result = _add_payer(conn, env, name="BlueCross BlueShield", payer_type="commercial",
                            edi_payer_id="BCBS001", submission_method="electronic")
        assert is_ok(result), result
        assert "id" in result
        assert result["name"] == "BlueCross BlueShield"
        assert result["payer_type"] == "commercial"

        # Verify payer was stored as active via get
        get_res = call_action(mod.health_get_payer, conn, ns(
            payer_id=result["id"], limit=50, offset=0,
        ))
        assert is_ok(get_res)
        assert get_res["payer_status"] == "active"

    def test_add_payer_missing_name(self, conn, env):
        result = call_action(mod.health_add_payer, conn, ns(
            company_id=env["company_id"],
            name=None,
            payer_type="commercial",
            edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
            submission_method=None, timely_filing_days=None, era_enrollment=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_add_payer_missing_payer_type(self, conn, env):
        result = call_action(mod.health_add_payer, conn, ns(
            company_id=env["company_id"],
            name="Test Payer",
            payer_type=None,
            edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
            submission_method=None, timely_filing_days=None, era_enrollment=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_add_payer_invalid_payer_type(self, conn, env):
        result = call_action(mod.health_add_payer, conn, ns(
            company_id=env["company_id"],
            name="Test Payer",
            payer_type="invalid_type",
            edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
            submission_method=None, timely_filing_days=None, era_enrollment=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_update_payer(self, conn, env):
        add_res = _add_payer(conn, env, name="Update Me Payer")
        assert is_ok(add_res)
        result = call_action(mod.health_update_payer, conn, ns(
            payer_id=add_res["id"],
            name="Updated Payer Name",
            payer_type=None,
            edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
            submission_method=None, timely_filing_days=None, era_enrollment=None,
            payer_status=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "name" in result["updated_fields"]

    def test_update_payer_not_found(self, conn, env):
        result = call_action(mod.health_update_payer, conn, ns(
            payer_id="nonexistent-id",
            name="Whatever",
            payer_type=None,
            edi_payer_id=None, electronic_filing_id=None,
            address=None, city=None, state=None, zip_code=None, phone=None,
            claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
            submission_method=None, timely_filing_days=None, era_enrollment=None,
            payer_status=None, notes=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_get_payer(self, conn, env):
        add_res = _add_payer(conn, env, name="Get Me Payer", payer_type="medicare")
        assert is_ok(add_res)
        result = call_action(mod.health_get_payer, conn, ns(
            payer_id=add_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["name"] == "Get Me Payer"
        assert result["payer_type"] == "medicare"

    def test_list_payers_by_type(self, conn, env):
        _add_payer(conn, env, name="Medicare Payer A", payer_type="medicare")
        _add_payer(conn, env, name="Commercial Payer A", payer_type="commercial")
        _add_payer(conn, env, name="Medicare Payer B", payer_type="medicare")

        result = call_action(mod.health_list_payers, conn, ns(
            company_id=env["company_id"],
            payer_type="medicare",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] == 2
        for row in result["rows"]:
            assert row["payer_type"] == "medicare"

    def test_list_payers_all(self, conn, env):
        _add_payer(conn, env, name="List All Payer", payer_type="medicaid")
        result = call_action(mod.health_list_payers, conn, ns(
            company_id=env["company_id"],
            payer_type=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1

    def test_link_payer_fee_schedule(self, conn, env):
        # Create payer
        payer_res = _add_payer(conn, env, name="Link FS Payer")
        assert is_ok(payer_res)

        # Create fee schedule
        fs_res = call_action(mod.health_add_fee_schedule, conn, ns(
            company_id=env["company_id"],
            fee_schedule_name="Test FS for Payer",
            description=None,
            effective_date="2026-01-01",
            expiration_date=None,
            fee_schedule_status=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(fs_res)

        # Link
        result = call_action(mod.health_link_payer_fee_schedule, conn, ns(
            payer_id=payer_res["id"],
            fee_schedule_id=fs_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["default_fee_schedule_id"] == fs_res["id"]

        # Verify via get
        get_res = call_action(mod.health_get_payer, conn, ns(
            payer_id=payer_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(get_res)
        assert get_res["default_fee_schedule_id"] == fs_res["id"]

    def test_link_payer_fee_schedule_not_found(self, conn, env):
        payer_res = _add_payer(conn, env, name="FS Not Found Payer")
        assert is_ok(payer_res)
        result = call_action(mod.health_link_payer_fee_schedule, conn, ns(
            payer_id=payer_res["id"],
            fee_schedule_id="nonexistent-fs-id",
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_payer_performance_report(self, conn, env):
        # Create a payer
        _add_payer(conn, env, name="Performance Payer", payer_type="commercial")
        result = call_action(mod.health_payer_performance_report, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "payers" in result
        assert result["payer_count"] >= 1
        for p in result["payers"]:
            assert "payer_id" in p
            assert "total_claims" in p
            assert "total_charged" in p
            assert "total_paid" in p


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestEligibility:
    def test_record_eligibility_check(self, conn, env):
        ins_res = _add_insurance(conn, env, payer_name="EligPayer", member_id="MEM-ELIG")
        assert is_ok(ins_res)

        result = call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            payer_id=None,
            coverage_status="active",
            check_method="electronic",
            copay="25.00",
            deductible="1500.00",
            deductible_met="500.00",
            coinsurance_pct="20",
            out_of_pocket_max="6000.00",
            oop_met="500.00",
            plan_begin_date="2026-01-01",
            plan_end_date="2026-12-31",
            in_network="1",
            prior_auth_required="0",
            notes="Verified via phone",
            checked_by="Front Desk",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert result["coverage_status"] == "active"

    def test_record_eligibility_check_missing_coverage(self, conn, env):
        ins_res = _add_insurance(conn, env, payer_name="MissingCov", member_id="MEM-MC")
        assert is_ok(ins_res)

        result = call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            payer_id=None,
            coverage_status=None,
            check_method=None,
            copay=None, deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_record_eligibility_check_invalid_insurance(self, conn, env):
        result = call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id="nonexistent-ins-id",
            payer_id=None,
            coverage_status="active",
            check_method=None,
            copay=None, deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_get_latest_eligibility(self, conn, env):
        import uuid as _uuid_mod
        ins_res = _add_insurance(conn, env, payer_name="LatestPayer", member_id="MEM-LAT")
        assert is_ok(ins_res)

        # Insert an older check directly with an earlier created_at timestamp
        conn.execute(
            """INSERT INTO healthclaw_eligibility_check
               (id, patient_id, patient_insurance_id, check_date, check_method,
                coverage_status, created_at)
               VALUES (?, ?, ?, '2026-01-01', 'phone', 'pending', '2026-01-01T00:00:00Z')""",
            (str(_uuid_mod.uuid4()), env["patient_id"], ins_res["id"])
        )
        conn.commit()

        # Record second (latest) check via the action (gets current timestamp)
        call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            payer_id=None,
            coverage_status="active",
            check_method="electronic",
            copay="30.00",
            deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_get_latest_eligibility, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["coverage_status"] == "active"
        assert result["copay"] == "30.00"

    def test_get_latest_eligibility_not_found(self, conn, env):
        ins_res = _add_insurance(conn, env, payer_name="NoCheck", member_id="MEM-NC")
        assert is_ok(ins_res)

        result = call_action(mod.health_get_latest_eligibility, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_list_eligibility_checks(self, conn, env):
        ins_res = _add_insurance(conn, env, payer_name="ListCheckPayer", member_id="MEM-LC")
        assert is_ok(ins_res)

        # Record two checks
        call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            payer_id=None,
            coverage_status="active",
            check_method="manual",
            copay=None, deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins_res["id"],
            payer_id=None,
            coverage_status="inactive",
            check_method="phone",
            copay=None, deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_list_eligibility_checks, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 2

    def test_check_eligibility_status_multiple_insurances(self, conn, env):
        # Create two insurance records
        ins1 = _add_insurance(conn, env, payer_name="Primary Payer", member_id="MEM-PRI")
        assert is_ok(ins1)
        ins2 = call_action(mod.health_add_patient_insurance, conn, ns(
            patient_id=env["patient_id"],
            company_id=env["company_id"],
            insurance_type="secondary",
            payer_name="Secondary Payer",
            payer_id=None, plan_name=None, plan_type=None,
            group_number=None, member_id="MEM-SEC",
            subscriber_name=None, subscriber_dob=None,
            subscriber_relationship=None,
            copay_amount=None, deductible=None, deductible_met=None,
            out_of_pocket_max=None, effective_date="2026-01-01",
            termination_date=None, preauth_required=None, status=None,
            limit=50, offset=0,
        ))
        assert is_ok(ins2)

        # Record eligibility for both
        call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins1["id"],
            payer_id=None,
            coverage_status="active",
            check_method="electronic",
            copay="25.00",
            deductible="1500.00",
            deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_record_eligibility_check, conn, ns(
            patient_id=env["patient_id"],
            patient_insurance_id=ins2["id"],
            payer_id=None,
            coverage_status="active",
            check_method="manual",
            copay="50.00",
            deductible=None, deductible_met=None,
            coinsurance_pct=None, out_of_pocket_max=None, oop_met=None,
            plan_begin_date=None, plan_end_date=None,
            in_network=None, prior_auth_required=None,
            notes=None, checked_by=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_check_eligibility_status, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["insurance_count"] == 2
        assert len(result["insurances"]) == 2
        for ins in result["insurances"]:
            assert ins["coverage_status"] == "active"
            assert ins["latest_check"] is not None

    def test_check_eligibility_status_no_checks(self, conn, env):
        """Patient with insurance but no eligibility checks should show 'unknown'."""
        ins_res = _add_insurance(conn, env, payer_name="NeverChecked", member_id="MEM-NOCHK")
        assert is_ok(ins_res)

        result = call_action(mod.health_check_eligibility_status, conn, ns(
            patient_id=env["patient_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["insurance_count"] >= 1
        # Find the insurance we just added — it should have no check
        nochk = [i for i in result["insurances"] if i["member_id"] == "MEM-NOCHK"]
        assert len(nochk) == 1
        assert nochk[0]["coverage_status"] == "unknown"
        assert nochk[0]["latest_check"] is None


# ─────────────────────────────────────────────────────────────────────────────
# ERA/835 Electronic Remittance Processing
# ─────────────────────────────────────────────────────────────────────────────

def _import_era_file(conn, env, claims_data, check_amount="1000.00", **kwargs):
    """Helper to import an ERA file with given claims_data."""
    import json as _json
    return call_action(mod.health_import_era_file, conn, ns(
        company_id=env["company_id"],
        received_date="2026-03-15",
        check_number=kwargs.get("check_number", "CHK-99001"),
        check_amount=check_amount,
        claims_data=_json.dumps(claims_data),
        payer_id=kwargs.get("payer_id"),
        file_name=kwargs.get("file_name", "ERA_835_20260315.txt"),
        eft_trace=kwargs.get("eft_trace"),
        notes=kwargs.get("notes"),
        limit=50, offset=0,
    ))


def _create_test_claim(conn, env, claim_number_prefix="CLM-TEST"):
    """Create a claim via billing action and return its result dict."""
    # First need an insurance record
    ins_res = call_action(mod.health_add_patient_insurance, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        insurance_type="primary",
        payer_name="ERA Test Payer",
        payer_id=None, plan_name=None, plan_type=None,
        group_number=None, member_id="MEM-ERA-001",
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None,
        copay_amount=None, deductible=None, deductible_met=None,
        out_of_pocket_max=None, effective_date="2026-01-01",
        termination_date=None, preauth_required=None, status=None,
        limit=50, offset=0,
    ))
    assert is_ok(ins_res), ins_res

    claim_res = call_action(mod.health_add_claim, conn, ns(
        company_id=env["company_id"],
        patient_id=env["patient_id"],
        encounter_id=env["encounter_id"],
        insurance_id=ins_res["id"],
        claim_date="2026-03-01",
        claim_type="professional",
        total_charge="500.00",
        total_allowed=None,
        total_paid=None,
        patient_responsibility=None,
        adjustment_amount=None,
        billing_provider_id=None,
        rendering_provider_id=None,
        place_of_service=None,
        filing_indicator=None,
        prior_auth_id=None,
        sales_invoice_id=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(claim_res), claim_res
    return claim_res


class TestERA:
    def test_import_era_file_happy_path(self, conn, env):
        """Import ERA file with 2 claims, verify header + details created."""
        claims = [
            {
                "patient_name": "Jane Smith",
                "claim_number": "UNKNOWN-001",
                "service_date": "2026-03-01",
                "billed_amount": "500.00",
                "allowed_amount": "400.00",
                "paid_amount": "360.00",
                "patient_responsibility": "40.00",
                "adjustment_amount": "100.00",
                "adjustment_codes": "CO-45",
                "remark_codes": "N362",
            },
            {
                "patient_name": "John Doe",
                "claim_number": "UNKNOWN-002",
                "service_date": "2026-03-02",
                "billed_amount": "200.00",
                "allowed_amount": "180.00",
                "paid_amount": "162.00",
                "patient_responsibility": "18.00",
                "adjustment_amount": "20.00",
                "adjustment_codes": "CO-45",
                "remark_codes": "N362",
            },
        ]
        result = _import_era_file(conn, env, claims, check_amount="522.00")
        assert is_ok(result), result
        assert result["claim_count"] == 2
        assert result["matched_count"] == 0
        assert result["check_amount"] == "522.00"
        assert len(result["details"]) == 2

        # Verify via get-era-file-details
        details_res = call_action(mod.health_get_era_file_details, conn, ns(
            era_file_id=result["id"],
            limit=50, offset=0,
        ))
        assert is_ok(details_res), details_res
        assert len(details_res["claim_details"]) == 2
        assert details_res["claim_count"] == 2

    def test_import_era_file_auto_match(self, conn, env):
        """Import ERA with claim_number matching existing claim -- verify matched."""
        claim_res = _create_test_claim(conn, env)
        claim_naming = claim_res["naming_series"]

        claims = [
            {
                "patient_name": "Jane Smith",
                "claim_number": claim_naming,
                "service_date": "2026-03-01",
                "billed_amount": "500.00",
                "allowed_amount": "400.00",
                "paid_amount": "360.00",
                "patient_responsibility": "40.00",
                "adjustment_amount": "100.00",
                "adjustment_codes": "CO-45",
                "remark_codes": "N362",
            },
        ]
        result = _import_era_file(conn, env, claims, check_amount="360.00")
        assert is_ok(result), result
        assert result["claim_count"] == 1
        assert result["matched_count"] == 1
        assert result["details"][0]["match_status"] == "matched"

    def test_import_era_file_unmatched(self, conn, env):
        """Import ERA with unknown claim_number -- verify unmatched."""
        claims = [
            {
                "patient_name": "Nobody",
                "claim_number": "CLM-NONEXISTENT-999",
                "service_date": "2026-03-01",
                "billed_amount": "100.00",
                "allowed_amount": "80.00",
                "paid_amount": "72.00",
                "patient_responsibility": "8.00",
                "adjustment_amount": "20.00",
                "adjustment_codes": "CO-45",
                "remark_codes": "N362",
            },
        ]
        result = _import_era_file(conn, env, claims, check_amount="72.00")
        assert is_ok(result), result
        assert result["claim_count"] == 1
        assert result["matched_count"] == 0
        assert result["details"][0]["match_status"] == "unmatched"

    def test_list_era_files(self, conn, env):
        """List ERA files with date filter."""
        claims = [{"patient_name": "A", "claim_number": "X", "billed_amount": "10.00",
                    "paid_amount": "8.00"}]
        r1 = _import_era_file(conn, env, claims, check_amount="8.00")
        assert is_ok(r1), r1

        result = call_action(mod.health_list_era_files, conn, ns(
            company_id=env["company_id"],
            status=None,
            date_from="2026-03-01",
            date_to="2026-03-31",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        assert len(result["rows"]) >= 1

    def test_get_era_file_details(self, conn, env):
        """Get ERA file returns header + claim details."""
        claims = [
            {"patient_name": "Detail A", "claim_number": "D-001",
             "billed_amount": "100.00", "paid_amount": "90.00"},
            {"patient_name": "Detail B", "claim_number": "D-002",
             "billed_amount": "200.00", "paid_amount": "180.00"},
        ]
        r1 = _import_era_file(conn, env, claims, check_amount="270.00")
        assert is_ok(r1), r1

        result = call_action(mod.health_get_era_file_details, conn, ns(
            era_file_id=r1["id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["check_number"] == "CHK-99001"
        assert result["check_amount"] == "270.00"
        assert len(result["claim_details"]) == 2
        names = [d["patient_name"] for d in result["claim_details"]]
        assert "Detail A" in names
        assert "Detail B" in names

    def test_auto_post_era(self, conn, env):
        """Auto-post matched claims: verify payment_posting created, claim status updated."""
        claim_res = _create_test_claim(conn, env)
        claim_naming = claim_res["naming_series"]
        claim_id = claim_res["id"]

        claims = [
            {
                "patient_name": "Jane Smith",
                "claim_number": claim_naming,
                "service_date": "2026-03-01",
                "billed_amount": "500.00",
                "allowed_amount": "400.00",
                "paid_amount": "500.00",
                "patient_responsibility": "0.00",
                "adjustment_amount": "0.00",
            },
        ]
        era_res = _import_era_file(conn, env, claims, check_amount="500.00")
        assert is_ok(era_res), era_res
        assert era_res["matched_count"] == 1

        # Auto-post
        post_res = call_action(mod.health_auto_post_era, conn, ns(
            era_file_id=era_res["id"],
            posted_by=None,
            limit=50, offset=0,
        ))
        assert is_ok(post_res), post_res
        assert post_res["posted_count"] == 1
        assert post_res["total_posted"] == "500.00"
        assert post_res["era_status"] == "posted"

        # Verify claim status updated to 'paid'
        claim_check = call_action(mod.health_get_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_ok(claim_check), claim_check
        assert claim_check["claim_status"] == "paid"
        assert claim_check["total_paid"] == "500.00"

        # Verify payment_posting was created
        pp_res = call_action(mod.health_list_payment_postings, conn, ns(
            claim_id=claim_id,
            patient_id=None,
            posting_type=None,
            company_id=None,
            limit=50, offset=0,
        ))
        assert is_ok(pp_res), pp_res
        assert pp_res["total_count"] >= 1
        found = [r for r in pp_res["rows"] if r["posting_type"] == "insurance_payment"]
        assert len(found) >= 1
        assert found[0]["amount"] == "500.00"

    def test_auto_post_era_skips_unmatched(self, conn, env):
        """Unmatched claims should not be posted."""
        claims = [
            {
                "patient_name": "Nobody",
                "claim_number": "CLM-GHOST-999",
                "billed_amount": "100.00",
                "paid_amount": "80.00",
            },
        ]
        era_res = _import_era_file(conn, env, claims, check_amount="80.00")
        assert is_ok(era_res), era_res
        assert era_res["matched_count"] == 0

        # Auto-post should fail (no matched claims)
        post_res = call_action(mod.health_auto_post_era, conn, ns(
            era_file_id=era_res["id"],
            posted_by=None,
            limit=50, offset=0,
        ))
        assert is_error(post_res)

    def test_era_reconciliation_report(self, conn, env):
        """Reconciliation report shows correct totals."""
        # Create a matched ERA + an unmatched ERA
        claim_res = _create_test_claim(conn, env)
        claim_naming = claim_res["naming_series"]

        # ERA 1: matched claim
        claims1 = [
            {
                "patient_name": "Jane Smith",
                "claim_number": claim_naming,
                "billed_amount": "500.00",
                "paid_amount": "450.00",
            },
        ]
        era1 = _import_era_file(conn, env, claims1, check_amount="450.00",
                                check_number="CHK-R-001")
        assert is_ok(era1), era1

        # ERA 2: unmatched claim
        claims2 = [
            {
                "patient_name": "Unknown Patient",
                "claim_number": "CLM-RECON-GHOST",
                "billed_amount": "200.00",
                "paid_amount": "180.00",
            },
        ]
        era2 = _import_era_file(conn, env, claims2, check_amount="180.00",
                                check_number="CHK-R-002")
        assert is_ok(era2), era2

        result = call_action(mod.health_era_reconciliation_report, conn, ns(
            company_id=env["company_id"],
            date_from=None,
            date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_files"] >= 2
        assert result["total_claims"] >= 2
        assert result["total_matched"] >= 1
        assert result["total_unmatched"] >= 1
        # Nothing posted yet, so total_posted should be "0.00"
        # and total_pending should include amounts from both files
        from decimal import Decimal
        assert Decimal(result["total_pending"]) >= Decimal("630.00")
