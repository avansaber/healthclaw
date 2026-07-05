"""Tests for HealthClaw B11-SAFETY: drug-interaction honesty fix + CRUD.

The `health-check-drug-interaction` action must NOT report an authoritative
"no interactions" clearance when the company simply has no reference data
loaded (a clinical false-negative). It returns the module's `not_configured`
shape until interaction pairs are configured for that company, and both the
honesty count and the match query are company-scoped so one clinic's data can
never flip another clinic's result (BDFL checkpoint-① condition 2).

Covers:
  - not_configured when the reference table is empty (for that company)
  - active + genuine interaction_count:0 when pairs exist but none match
  - active + a real match found
  - two-company scope isolation (A loads pairs -> B still not_configured)
  - add / list writers (exact-value asserts) + validation guards
"""
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query, seed_company

mod = load_db_query()


def _add_medication(conn, company_id, name):
    """Add a medication and return its id."""
    res = call_action(mod.health_add_medication, conn, ns(
        company_id=company_id, name=name,
        dea_schedule=None, unit_price=None,
        quantity_on_hand=None, reorder_level=None,
        generic_name=None, ndc_code=None, dosage_form=None,
        strength=None, manufacturer=None, notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(res), res
    return res["id"]


def _add_interaction(conn, company_id, med_a, med_b, severity="moderate",
                     description="Interaction", recommendation=None):
    return call_action(mod.health_add_drug_interaction, conn, ns(
        company_id=company_id, medication_a_id=med_a, medication_b_id=med_b,
        severity=severity, description=description, recommendation=recommendation,
        limit=50, offset=0,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# Honesty fix: not_configured vs genuine-zero vs real match
# ═══════════════════════════════════════════════════════════════════════════

class TestDrugInteractionHonesty:
    def test_not_configured_when_reference_empty(self, conn, env):
        """No reference pairs loaded for this company -> not_configured, never a
        false 'no interactions found' clearance."""
        med = _add_medication(conn, env["company_id"], "Warfarin")
        result = call_action(mod.health_check_drug_interaction, conn, ns(
            medication_id=med, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "not_configured"
        assert result["reference_pair_count"] == 0
        assert result["interaction_count"] == 0
        assert result["interactions"] == []

    def test_active_genuine_zero_when_pairs_exist_but_none_match(self, conn, env):
        """Pairs exist for the company but not involving this medication -> a
        genuine 'checked, none found' (feature_status active), distinct from
        not_configured."""
        a = _add_medication(conn, env["company_id"], "Aspirin")
        b = _add_medication(conn, env["company_id"], "Ibuprofen")
        assert is_ok(_add_interaction(conn, env["company_id"], a, b,
                                      severity="moderate", description="NSAID overlap"))

        c = _add_medication(conn, env["company_id"], "Lisinopril")
        result = call_action(mod.health_check_drug_interaction, conn, ns(
            medication_id=c, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "active"
        assert result["reference_pair_count"] == 1
        assert result["interaction_count"] == 0
        assert "scope_note" in result

    def test_active_finds_matching_interaction(self, conn, env):
        a = _add_medication(conn, env["company_id"], "Warfarin")
        b = _add_medication(conn, env["company_id"], "Aspirin")
        add = _add_interaction(conn, env["company_id"], a, b,
                               severity="major", description="Bleeding risk",
                               recommendation="Monitor INR")
        assert is_ok(add), add
        assert add["severity"] == "major"

        result = call_action(mod.health_check_drug_interaction, conn, ns(
            medication_id=a, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "active"
        assert result["interaction_count"] == 1
        inter = result["interactions"][0]
        assert inter["severity"] == "major"
        assert inter["interacting_medication_id"] == b

    def test_two_company_scope_isolation(self, conn, env):
        """BDFL condition 2: company A loading pairs must NOT flip company B from
        not_configured to a false 'checked, clean'."""
        a1 = _add_medication(conn, env["company_id"], "Warfarin A")
        a2 = _add_medication(conn, env["company_id"], "Aspirin A")
        assert is_ok(_add_interaction(conn, env["company_id"], a1, a2,
                                      severity="major", description="Bleeding risk"))

        company_b = seed_company(conn, "Other Clinic", "OTH")
        b_med = _add_medication(conn, company_b, "Warfarin B")
        result = call_action(mod.health_check_drug_interaction, conn, ns(
            medication_id=b_med, limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["feature_status"] == "not_configured"
        assert result["reference_pair_count"] == 0
        assert result["interaction_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════
# CRUD writers
# ═══════════════════════════════════════════════════════════════════════════

class TestDrugInteractionCRUD:
    def test_add_and_list(self, conn, env):
        a = _add_medication(conn, env["company_id"], "Metformin")
        b = _add_medication(conn, env["company_id"], "Contrast Dye")
        add = _add_interaction(conn, env["company_id"], a, b,
                               severity="contraindicated",
                               description="Lactic acidosis risk",
                               recommendation="Hold metformin 48h")
        assert is_ok(add), add

        listed = call_action(mod.health_list_drug_interactions, conn, ns(
            company_id=env["company_id"], medication_id=a, limit=50, offset=0,
        ))
        assert is_ok(listed), listed
        assert listed["total_count"] == 1
        assert listed["rows"][0]["severity"] == "contraindicated"
        assert listed["rows"][0]["description"] == "Lactic acidosis risk"
        assert listed["rows"][0]["recommendation"] == "Hold metformin 48h"

    def test_list_company_scoped(self, conn, env):
        """List is company-scoped — company B's pairs never leak into A's list."""
        a = _add_medication(conn, env["company_id"], "DrugA1")
        b = _add_medication(conn, env["company_id"], "DrugA2")
        assert is_ok(_add_interaction(conn, env["company_id"], a, b))

        company_b = seed_company(conn, "B Clinic", "BCL")
        listed_b = call_action(mod.health_list_drug_interactions, conn, ns(
            company_id=company_b, medication_id=None, limit=50, offset=0,
        ))
        assert is_ok(listed_b), listed_b
        assert listed_b["total_count"] == 0

    def test_invalid_severity_rejected(self, conn, env):
        a = _add_medication(conn, env["company_id"], "DrugX")
        b = _add_medication(conn, env["company_id"], "DrugY")
        result = _add_interaction(conn, env["company_id"], a, b,
                                  severity="fatal", description="bad")
        assert is_error(result)

    def test_same_medication_rejected(self, conn, env):
        a = _add_medication(conn, env["company_id"], "DrugZ")
        result = _add_interaction(conn, env["company_id"], a, a,
                                  severity="minor", description="self")
        assert is_error(result)

    def test_cross_company_medication_rejected(self, conn, env):
        a = _add_medication(conn, env["company_id"], "DrugA")
        company_b = seed_company(conn, "B Clinic", "BCL")
        b = _add_medication(conn, company_b, "DrugB")
        result = _add_interaction(conn, env["company_id"], a, b,
                                  severity="minor", description="cross")
        assert is_error(result)
