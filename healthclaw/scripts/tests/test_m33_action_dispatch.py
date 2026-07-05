"""M33 close-out: faucet-level dispatch tests for the 4 new B11 actions.

The feature tests in test_drug_interaction.py / test_phase11.py call the Python
functions directly, which never exercises the kebab-case name -> handler binding
the router dispatches through (and leaves the action names invisible to the
necessity register's tested-detector). These tests resolve each new action from
its sub-script ACTIONS registry BY LITERAL NAME — the same lookup the healthclaw
aggregate router performs — and drive one happy path each:
  health-add-drug-interaction / health-list-drug-interactions
  health-add-scheduling-rule  / health-list-scheduling-rules
(health-check-drug-interaction predates M33's honesty fix but is asserted here
too since the B11-SAFETY story depends on its binding.)
"""
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPTS_DIR = os.path.dirname(_TESTS_DIR)
for p in (_TESTS_DIR, _SCRIPTS_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

import adv_pharmacy
import adv_reports_v2
from health_helpers import call_action, ns, is_ok


def _add_med(conn, company_id, name):
    res = call_action(
        adv_pharmacy.ACTIONS["health-add-medication"]
        if "health-add-medication" in adv_pharmacy.ACTIONS
        else __import__("db_query").health_add_medication,
        conn,
        ns(company_id=company_id, name=name, dea_schedule=None, unit_price=None,
           quantity_on_hand=None, reorder_level=None, generic_name=None,
           ndc_code=None, dosage_form=None, strength=None, manufacturer=None,
           notes=None, limit=50, offset=0))
    assert is_ok(res), res
    return res["id"]


class TestDrugInteractionDispatch:
    def test_add_and_list_dispatch_by_action_name(self, conn, env):
        company_id = env["company_id"]
        med_a = _add_med(conn, company_id, "Warfarin")
        med_b = _add_med(conn, company_id, "Aspirin")

        add = adv_pharmacy.ACTIONS["health-add-drug-interaction"]
        res = call_action(add, conn, ns(
            company_id=company_id, medication_a_id=med_a, medication_b_id=med_b,
            severity="major", description="Bleeding risk", recommendation=None,
            limit=50, offset=0))
        assert is_ok(res), res

        lst = adv_pharmacy.ACTIONS["health-list-drug-interactions"]
        res = call_action(lst, conn, ns(company_id=company_id, limit=50, offset=0))
        assert is_ok(res), res
        assert res["total_count"] == 1

    def test_check_dispatches_by_action_name(self, conn, env):
        company_id = env["company_id"]
        med = _add_med(conn, company_id, "Lisinopril")
        chk = adv_pharmacy.ACTIONS["health-check-drug-interaction"]
        res = call_action(chk, conn, ns(
            company_id=company_id, medication_id=med, limit=50, offset=0))
        assert is_ok(res), res
        assert res["feature_status"] == "not_configured"


class TestSchedulingRuleDispatch:
    def test_add_and_list_dispatch_by_action_name(self, conn, env):
        company_id = env["company_id"]
        add = adv_reports_v2.ACTIONS["health-add-scheduling-rule"]
        res = call_action(add, conn, ns(
            company_id=company_id, rule_name="Max daily slots",
            rule_type="max_per_day", rule_value="12",
            provider_id=None, description=None, limit=50, offset=0))
        assert is_ok(res), res

        lst = adv_reports_v2.ACTIONS["health-list-scheduling-rules"]
        res = call_action(lst, conn, ns(company_id=company_id, provider_id=None,
                                        rule_type=None, status=None,
                                        limit=50, offset=0))
        assert is_ok(res), res
        assert res["total_count"] == 1
