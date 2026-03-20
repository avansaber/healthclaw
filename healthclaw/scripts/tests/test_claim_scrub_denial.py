"""Tests for HealthClaw H3 (Claim Scrubbing) and H5 (Denial Management).

Actions tested:
  - health-scrub-claim
  - health-submit-claim (scrub integration)
  - health-record-denial
  - health-submit-appeal
  - health-resolve-appeal
  - health-list-denied-claims
  - health-denial-trend-report
  - health-appeal-success-rate-report
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers: seed a full claim with lines for scrub/denial tests
# ─────────────────────────────────────────────────────────────────────────────

def _seed_insurance(conn, env):
    """Create a patient insurance record for claim tests."""
    res = call_action(mod.health_add_patient_insurance, conn, ns(
        patient_id=env["patient_id"],
        company_id=env["company_id"],
        insurance_type="primary",
        payer_name="TestPayer",
        payer_id=None, plan_name=None, plan_type=None,
        group_number=None, member_id="MEM-SCRUB",
        subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None,
        copay_amount=None, deductible=None, deductible_met=None,
        out_of_pocket_max=None, effective_date="2026-01-01",
        termination_date=None, preauth_required=None, status=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _seed_charge(conn, env):
    """Create a charge for claim line tests."""
    res = call_action(mod.health_add_charge, conn, ns(
        company_id=env["company_id"],
        encounter_id=env["encounter_id"],
        patient_id=env["patient_id"],
        provider_id=env["provider_id"],
        cpt_code="99213",
        charge_amount="150.00",
        service_date="2026-03-15",
        procedure_id=None,
        fee_schedule_id=None,
        units="1",
        modifier=None,
        modifiers=None,
        diagnosis_ids=None,
        place_of_service="11",
        rendering_provider_id=None,
        charge_status=None,
        allowed_amount=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _seed_claim(conn, env, ins_id):
    """Create a draft claim."""
    res = call_action(mod.health_add_claim, conn, ns(
        company_id=env["company_id"],
        patient_id=env["patient_id"],
        encounter_id=env["encounter_id"],
        insurance_id=ins_id,
        claim_type="professional",
        claim_date="2026-03-20",
        total_charge="150.00",
        billing_provider_id=env["provider_id"],
        rendering_provider_id=env["provider_id"],
        filing_indicator=None,
        notes=None,
        claim_status=None, total_allowed=None, total_paid=None,
        patient_responsibility=None, adjustment_amount=None,
        sales_invoice_id=None, denial_reason=None, appeal_deadline=None,
        prior_auth_id=None, place_of_service=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _seed_claim_line(conn, claim_id, charge_id, cpt="99213", dx_pointers="1"):
    """Add a claim line."""
    res = call_action(mod.health_add_claim_line, conn, ns(
        claim_id=claim_id,
        charge_id=charge_id,
        cpt_code=cpt,
        line_number="1",
        modifiers=None,
        diagnosis_pointers=dx_pointers,
        units="1",
        charge_amount="150.00",
        allowed_amount=None,
        paid_amount=None,
        adjustment_amount=None,
        patient_amount=None,
        denial_reason=None,
        remark_codes=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _seed_full_claim(conn, env):
    """Create a complete draft claim with insurance, charge, and claim line."""
    ins_id = _seed_insurance(conn, env)
    charge_id = _seed_charge(conn, env)
    claim_id = _seed_claim(conn, env, ins_id)
    _seed_claim_line(conn, claim_id, charge_id)
    return claim_id, ins_id, charge_id


# ─────────────────────────────────────────────────────────────────────────────
# H3: Claim Scrubbing
# ─────────────────────────────────────────────────────────────────────────────

class TestClaimScrub:
    def test_scrub_claim_valid(self, conn, env):
        """Scrub a valid claim -- should pass with no errors."""
        claim_id, _, _ = _seed_full_claim(conn, env)
        result = call_action(mod.health_scrub_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["pass"] is True
        assert result["errors"] == []

    def test_scrub_claim_no_claim_lines(self, conn, env):
        """Scrub a claim with no lines -- should fail."""
        ins_id = _seed_insurance(conn, env)
        claim_id = _seed_claim(conn, env, ins_id)
        result = call_action(mod.health_scrub_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["pass"] is False
        assert any("No claim lines" in e for e in result["errors"])

    def test_scrub_claim_invalid_npi(self, conn, env):
        """Scrub a claim where rendering provider has a bad NPI."""
        claim_id, _, _ = _seed_full_claim(conn, env)
        # Inject a bad NPI into the employee table (add npi column if missing)
        try:
            conn.execute("ALTER TABLE employee ADD COLUMN npi TEXT")
        except Exception:
            pass  # column already exists
        conn.execute("UPDATE employee SET npi = ? WHERE id = ?",
                     ("1234567890", env["provider_id"]))
        conn.commit()

        result = call_action(mod.health_scrub_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["pass"] is False
        assert any("NPI" in e and "invalid" in e for e in result["errors"])

    def test_scrub_claim_duplicate_detection(self, conn, env):
        """Scrub a claim that is a duplicate -- should produce a warning."""
        ins_id = _seed_insurance(conn, env)
        charge_id = _seed_charge(conn, env)

        # First claim (submit it)
        claim_id_1 = _seed_claim(conn, env, ins_id)
        _seed_claim_line(conn, claim_id_1, charge_id)
        submit_res = call_action(mod.health_submit_claim, conn, ns(
            claim_id=claim_id_1,
            limit=50, offset=0,
        ))
        assert is_ok(submit_res), submit_res

        # Second claim (duplicate -- same patient, payer, service_date, cpt)
        claim_id_2 = _seed_claim(conn, env, ins_id)
        _seed_claim_line(conn, claim_id_2, charge_id)

        result = call_action(mod.health_scrub_claim, conn, ns(
            claim_id=claim_id_2,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        # Duplicate should show as a warning
        assert any("duplicate" in w.lower() for w in result["warnings"])

    def test_submit_claim_calls_scrub(self, conn, env):
        """Submit should reject a claim that fails scrub (no lines)."""
        ins_id = _seed_insurance(conn, env)
        claim_id = _seed_claim(conn, env, ins_id)
        # Do NOT add claim lines -- scrub should fail
        result = call_action(mod.health_submit_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_error(result), result
        msg = (result.get("error", "") or result.get("message", "")).lower()
        assert "scrub failed" in msg or "no claim lines" in msg


# ─────────────────────────────────────────────────────────────────────────────
# H5: Denial Management
# ─────────────────────────────────────────────────────────────────────────────

class TestDenialManagement:
    def _submit_claim(self, conn, env):
        """Helper: create and submit a claim, return claim_id."""
        claim_id, ins_id, charge_id = _seed_full_claim(conn, env)
        res = call_action(mod.health_submit_claim, conn, ns(
            claim_id=claim_id,
            limit=50, offset=0,
        ))
        assert is_ok(res), res
        return claim_id

    def test_record_denial(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        result = call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="CO",
            denial_code="16",
            denial_reason="Claim lacks information",
            denial_date="2026-03-20",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["claim_status"] == "denied"
        assert result["denial_category"] == "CO"
        assert result["denial_code"] == "16"

    def test_record_denial_invalid_category(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        result = call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="XX",
            denial_code="16",
            denial_reason=None,
            denial_date=None,
            limit=50, offset=0,
        ))
        assert is_error(result)

    def test_submit_appeal(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        # First deny it
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="PR",
            denial_code="1",
            denial_reason="Deductible not met",
            denial_date="2026-03-20",
            limit=50, offset=0,
        ))
        # Now appeal
        result = call_action(mod.health_submit_appeal, conn, ns(
            claim_id=claim_id,
            appeal_method="written",
            appeal_reference="APL-001",
            notes="Additional documentation attached",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["claim_status"] == "appealed"
        assert "appeal_submitted_date" in result

    def test_resolve_appeal_overturned(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="CO",
            denial_code="4",
            denial_reason=None, denial_date=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_submit_appeal, conn, ns(
            claim_id=claim_id,
            appeal_method="online",
            appeal_reference=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_resolve_appeal, conn, ns(
            claim_id=claim_id,
            appeal_outcome="overturned",
            appeal_amount_recovered="150.00",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["claim_status"] == "accepted"
        assert result["appeal_outcome"] == "overturned"

    def test_resolve_appeal_upheld(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="OA",
            denial_code="18",
            denial_reason=None, denial_date=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_submit_appeal, conn, ns(
            claim_id=claim_id,
            appeal_method="phone",
            appeal_reference=None, notes=None,
            limit=50, offset=0,
        ))
        result = call_action(mod.health_resolve_appeal, conn, ns(
            claim_id=claim_id,
            appeal_outcome="upheld",
            appeal_amount_recovered=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["claim_status"] == "denied"
        assert result["appeal_outcome"] == "upheld"

    def test_list_denied_claims(self, conn, env):
        claim_id = self._submit_claim(conn, env)
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id,
            denial_category="PI",
            denial_code="119",
            denial_reason=None,
            denial_date="2026-03-20",
            limit=50, offset=0,
        ))
        result = call_action(mod.health_list_denied_claims, conn, ns(
            company_id=env["company_id"],
            payer_name=None,
            denial_category=None,
            date_from=None, date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        found = any(r["id"] == claim_id for r in result["rows"])
        assert found, f"Denied claim {claim_id} not in list"

    def test_denial_trend_report(self, conn, env):
        # Create and deny two claims
        for code in ("16", "16"):
            cid = self._submit_claim(conn, env)
            call_action(mod.health_record_denial, conn, ns(
                claim_id=cid,
                denial_category="CO",
                denial_code=code,
                denial_reason=None,
                denial_date="2026-03-20",
                limit=50, offset=0,
            ))
        result = call_action(mod.health_denial_trend_report, conn, ns(
            company_id=env["company_id"],
            months="6",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_denials"] >= 2
        assert len(result["trends"]) >= 1

    def test_appeal_success_rate_report(self, conn, env):
        # Create, deny, appeal, resolve 2 claims
        claim_id_1 = self._submit_claim(conn, env)
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id_1,
            denial_category="CO", denial_code="4",
            denial_reason=None, denial_date=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_submit_appeal, conn, ns(
            claim_id=claim_id_1,
            appeal_method="written", appeal_reference=None, notes=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_resolve_appeal, conn, ns(
            claim_id=claim_id_1,
            appeal_outcome="overturned",
            appeal_amount_recovered="200.00",
            limit=50, offset=0,
        ))

        claim_id_2 = self._submit_claim(conn, env)
        call_action(mod.health_record_denial, conn, ns(
            claim_id=claim_id_2,
            denial_category="PR", denial_code="1",
            denial_reason=None, denial_date=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_submit_appeal, conn, ns(
            claim_id=claim_id_2,
            appeal_method="online", appeal_reference=None, notes=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_resolve_appeal, conn, ns(
            claim_id=claim_id_2,
            appeal_outcome="upheld",
            appeal_amount_recovered=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_appeal_success_rate_report, conn, ns(
            company_id=env["company_id"],
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["appeals_submitted"] >= 2
        assert result["resolved"] >= 2
        assert result["outcomes"]["overturned"] >= 1
        assert result["outcomes"]["upheld"] >= 1
        # 1 overturned out of 2 resolved = 50%
        assert float(result["success_rate_pct"]) > 0
        assert result["total_amount_recovered"] == "200.00"
