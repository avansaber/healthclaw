"""Tests for HealthClaw Compliance domain (Phase 2).

Actions tested (PHI Access):
  - health-log-phi-access
  - health-phi-access-report
  - health-phi-access-anomaly-check
Actions tested (Good Faith Estimate):
  - health-generate-good-faith-estimate
  - health-list-good-faith-estimates
  - health-provide-good-faith-estimate
Actions tested (MIPS Quality Measures):
  - health-add-quality-measure
  - health-list-quality-measures
  - health-calculate-measure-result
  - health-mips-performance-dashboard
  - health-mips-submission-report
"""
import json
import pytest
from health_helpers import call_action, ns, is_error, is_ok, load_db_query

mod = load_db_query()


# ─────────────────────────────────────────────────────────────────────────────
# PHI Access Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _log_phi(conn, env, access_type="view", data_category="clinical", **kwargs):
    """Log a PHI access event and return the result dict."""
    return call_action(mod.health_log_phi_access, conn, ns(
        patient_id=env["patient_id"],
        access_type=access_type,
        data_category=data_category,
        user_id=kwargs.get("user_id"),
        action_name=kwargs.get("action_name"),
        resource_id=kwargs.get("resource_id"),
        ip_address=kwargs.get("ip_address"),
        user_agent=kwargs.get("user_agent"),
        access_reason=kwargs.get("access_reason"),
        break_the_glass=kwargs.get("break_the_glass"),
        limit=50, offset=0,
    ))


# ─────────────────────────────────────────────────────────────────────────────
# GFE Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _create_fee_schedule_with_items(conn, env, cpt_codes_prices):
    """Create a fee schedule with items. cpt_codes_prices = [(cpt, price), ...]"""
    fs_res = call_action(mod.health_add_fee_schedule, conn, ns(
        company_id=env["company_id"],
        fee_schedule_name="GFE Test Fee Schedule",
        description=None,
        effective_date="2026-01-01",
        expiration_date=None,
        fee_schedule_status=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(fs_res), fs_res

    for cpt, price in cpt_codes_prices:
        item_res = call_action(mod.health_add_fee_schedule_item, conn, ns(
            fee_schedule_id=fs_res["id"],
            cpt_code=cpt,
            description=f"Procedure {cpt}",
            standard_charge=price,
            allowed_amount=price,
            unit_count=None,
            modifier=None,
            limit=50, offset=0,
        ))
        assert is_ok(item_res), item_res

    return fs_res


def _create_payer_with_fs(conn, env, fs_id):
    """Create a payer linked to a fee schedule."""
    payer_res = call_action(mod.health_add_payer, conn, ns(
        company_id=env["company_id"],
        name="GFE Test Payer",
        payer_type="commercial",
        edi_payer_id=None, electronic_filing_id=None,
        address=None, city=None, state=None, zip_code=None, phone=None,
        claims_address=None, claims_city=None, claims_state=None, claims_zip=None,
        submission_method=None, timely_filing_days=None, era_enrollment=None,
        notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(payer_res), payer_res

    # Link fee schedule
    link_res = call_action(mod.health_link_payer_fee_schedule, conn, ns(
        payer_id=payer_res["id"],
        fee_schedule_id=fs_id,
        limit=50, offset=0,
    ))
    assert is_ok(link_res), link_res

    return payer_res


# ─────────────────────────────────────────────────────────────────────────────
# MIPS Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _add_measure(conn, env, measure_id="MIPS-001", name="Test Measure",
                 category="quality", **kwargs):
    """Create a quality measure and return the result dict."""
    return call_action(mod.health_add_quality_measure, conn, ns(
        company_id=env["company_id"],
        measure_id=measure_id,
        name=name,
        category=category,
        description=kwargs.get("description"),
        numerator_criteria=kwargs.get("numerator_criteria"),
        denominator_criteria=kwargs.get("denominator_criteria"),
        exclusion_criteria=kwargs.get("exclusion_criteria"),
        measure_type=kwargs.get("measure_type"),
        reporting_period=kwargs.get("reporting_period"),
        benchmark=kwargs.get("benchmark"),
        limit=50, offset=0,
    ))


# ═══════════════════════════════════════════════════════════════════════════
# H9: PHI Access Audit
# ═══════════════════════════════════════════════════════════════════════════

class TestPHIAccess:
    def test_log_phi_access_happy_path(self, conn, env):
        result = _log_phi(conn, env, access_type="view", data_category="clinical",
                          user_id="user-abc", action_name="health-get-patient",
                          resource_id=env["patient_id"], ip_address="192.168.1.1",
                          user_agent="Mozilla/5.0", access_reason="Routine visit")
        assert is_ok(result), result
        assert "id" in result
        assert result["patient_id"] == env["patient_id"]
        assert result["access_type"] == "view"
        assert result["data_category"] == "clinical"
        assert result["break_the_glass"] == 0

    def test_log_phi_access_break_the_glass_requires_reason(self, conn, env):
        # Without reason -- should fail
        result = _log_phi(conn, env, access_type="view", data_category="clinical",
                          user_id="user-emergency", break_the_glass="1")
        assert is_error(result)

        # With reason -- should succeed
        result2 = _log_phi(conn, env, access_type="view", data_category="clinical",
                           user_id="user-emergency", break_the_glass="1",
                           access_reason="Emergency override for unresponsive patient")
        assert is_ok(result2), result2
        assert result2["break_the_glass"] == 1

    def test_phi_access_report_by_patient(self, conn, env):
        _log_phi(conn, env, access_type="view", data_category="demographics", user_id="user-1")
        _log_phi(conn, env, access_type="edit", data_category="clinical", user_id="user-2")

        result = call_action(mod.health_phi_access_report, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            user_id=None,
            date_from=None,
            date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 2
        for row in result["rows"]:
            assert row["patient_id"] == env["patient_id"]

    def test_phi_access_report_by_user(self, conn, env):
        _log_phi(conn, env, access_type="view", data_category="billing", user_id="target-user")
        _log_phi(conn, env, access_type="print", data_category="insurance", user_id="other-user")

        result = call_action(mod.health_phi_access_report, conn, ns(
            company_id=env["company_id"],
            patient_id=None,
            user_id="target-user",
            date_from=None,
            date_to=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 1
        for row in result["rows"]:
            assert row["user_id"] == "target-user"

    def test_phi_access_anomaly_high_volume(self, conn, env):
        """User accessing >50 unique patients should be flagged."""
        # We need >50 unique patients -- create them and log access
        import uuid as _uuid_mod
        now = "2026-01-01T00:00:00Z"
        for i in range(55):
            pid = str(_uuid_mod.uuid4())
            conn.execute(
                """INSERT INTO healthclaw_patient
                   (id, naming_series, first_name, last_name, full_name,
                    date_of_birth, gender, status, company_id, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, '1990-01-01', 'male', 'active', ?, ?, ?)""",
                (pid, f"PAT-VOL-{i:03d}", f"Vol{i}", "Patient", f"Vol{i} Patient",
                 env["company_id"], now, now)
            )
            conn.execute(
                """INSERT INTO healthclaw_phi_access_log
                   (id, user_id, patient_id, access_type, data_category, created_at)
                   VALUES (?, ?, ?, 'view', 'clinical', ?)""",
                (str(_uuid_mod.uuid4()), "high-vol-user", pid, _now_iso())
            )
        conn.commit()

        result = call_action(mod.health_phi_access_anomaly_check, conn, ns(
            company_id=env["company_id"],
            days="30",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        high_vol = [a for a in result["anomalies"] if a["type"] == "high_volume_access"]
        assert len(high_vol) >= 1
        assert high_vol[0]["user_id"] == "high-vol-user"
        assert high_vol[0]["severity"] == "warning"

    def test_phi_access_anomaly_after_hours(self, conn, env):
        """Access outside 6am-10pm should be flagged."""
        import uuid as _uuid_mod
        from datetime import datetime, timezone, timedelta
        # Insert access at 3am UTC, 1 day ago (within the 30-day lookback window).
        # Use a dynamic timestamp so the test does not age out of the window.
        night_dt = (datetime.now(timezone.utc) - timedelta(days=1)).replace(
            hour=3, minute=0, second=0, microsecond=0
        )
        night_ts = night_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT INTO healthclaw_phi_access_log
               (id, user_id, patient_id, access_type, data_category, created_at)
               VALUES (?, ?, ?, 'view', 'clinical', ?)""",
            (str(_uuid_mod.uuid4()), "night-user", env["patient_id"], night_ts)
        )
        conn.commit()

        result = call_action(mod.health_phi_access_anomaly_check, conn, ns(
            company_id=env["company_id"],
            days="30",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        after_hours = [a for a in result["anomalies"] if a["type"] == "after_hours_access"
                       and a.get("user_id") == "night-user"]
        assert len(after_hours) >= 1
        assert after_hours[0]["severity"] == "info"

    def test_phi_access_anomaly_break_the_glass(self, conn, env):
        """Break-the-glass access should be flagged as critical."""
        _log_phi(conn, env, access_type="view", data_category="clinical",
                 user_id="btg-user", break_the_glass="1",
                 access_reason="Emergency")

        result = call_action(mod.health_phi_access_anomaly_check, conn, ns(
            company_id=env["company_id"],
            days="30",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        btg = [a for a in result["anomalies"] if a["type"] == "break_the_glass"
               and a.get("user_id") == "btg-user"]
        assert len(btg) >= 1
        assert btg[0]["severity"] == "critical"


# Helper for tests -- need _now_iso accessible
from datetime import datetime, timezone
_now_iso = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ═══════════════════════════════════════════════════════════════════════════
# H10: Good Faith Estimate
# ═══════════════════════════════════════════════════════════════════════════

class TestGoodFaithEstimate:
    def test_generate_gfe_happy_path(self, conn, env):
        """Generate GFE with fee schedule items -- verify itemized breakdown."""
        fs = _create_fee_schedule_with_items(conn, env, [
            ("99213", "150.00"),
            ("85025", "45.00"),
        ])

        result = call_action(mod.health_generate_good_faith_estimate, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            procedure_codes=json.dumps(["99213", "85025"]),
            provider_id=env["provider_id"],
            diagnosis_codes=json.dumps(["Z00.00"]),
            payer_id=None,
            notes="Annual checkup estimate",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert "id" in result
        assert result["total_estimate"] == "195.00"
        assert result["gfe_status"] == "draft"
        assert len(result["items"]) == 2
        assert result["insurance_applied"] == 0

        # Verify items
        cpts = [i["cpt_code"] for i in result["items"]]
        assert "99213" in cpts
        assert "85025" in cpts

    def test_generate_gfe_with_payer(self, conn, env):
        """Generate GFE with payer -- verify insurance estimate applied."""
        fs = _create_fee_schedule_with_items(conn, env, [
            ("99213", "150.00"),
            ("85025", "45.00"),
        ])
        payer = _create_payer_with_fs(conn, env, fs["id"])

        result = call_action(mod.health_generate_good_faith_estimate, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            procedure_codes=json.dumps(["99213", "85025"]),
            provider_id=None,
            diagnosis_codes=None,
            payer_id=payer["id"],
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["insurance_applied"] == 1
        assert result["total_estimate"] == "195.00"
        # With payer fee schedule, allowed = standard_charge,
        # so insurance pays full amount, patient responsibility = 0
        from decimal import Decimal
        assert Decimal(result["estimated_insurance_payment"]) == Decimal("195.00")
        assert Decimal(result["estimated_patient_responsibility"]) == Decimal("0.00")

    def test_generate_gfe_no_fee_schedule(self, conn, env):
        """Generate GFE with unknown CPT codes -- items show 0 charge."""
        result = call_action(mod.health_generate_good_faith_estimate, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            procedure_codes=json.dumps(["UNKNOWN-CPT-1", "UNKNOWN-CPT-2"]),
            provider_id=None,
            diagnosis_codes=None,
            payer_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_estimate"] == "0.00"
        for item in result["items"]:
            assert item["standard_charge"] == "0.00"

    def test_list_gfe(self, conn, env):
        """List GFEs for a patient."""
        _create_fee_schedule_with_items(conn, env, [("99213", "100.00")])

        # Generate two estimates
        for _ in range(2):
            call_action(mod.health_generate_good_faith_estimate, conn, ns(
                company_id=env["company_id"],
                patient_id=env["patient_id"],
                procedure_codes=json.dumps(["99213"]),
                provider_id=None,
                diagnosis_codes=None,
                payer_id=None,
                notes=None,
                limit=50, offset=0,
            ))

        result = call_action(mod.health_list_good_faith_estimates, conn, ns(
            patient_id=env["patient_id"],
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 2

    def test_provide_gfe(self, conn, env):
        """Provide GFE -- verify status changes to 'provided'."""
        _create_fee_schedule_with_items(conn, env, [("99213", "100.00")])

        gen_res = call_action(mod.health_generate_good_faith_estimate, conn, ns(
            company_id=env["company_id"],
            patient_id=env["patient_id"],
            procedure_codes=json.dumps(["99213"]),
            provider_id=None,
            diagnosis_codes=None,
            payer_id=None,
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(gen_res), gen_res
        assert gen_res["gfe_status"] == "draft"

        provide_res = call_action(mod.health_provide_good_faith_estimate, conn, ns(
            estimate_id=gen_res["id"],
            limit=50, offset=0,
        ))
        assert is_ok(provide_res), provide_res
        assert provide_res["gfe_status"] == "provided"
        assert provide_res["provided_at"] is not None

        # Verify via list (filter by status)
        list_res = call_action(mod.health_list_good_faith_estimates, conn, ns(
            patient_id=env["patient_id"],
            status="provided",
            limit=50, offset=0,
        ))
        assert is_ok(list_res), list_res
        ids = [r["id"] for r in list_res["rows"]]
        assert gen_res["id"] in ids


# ═══════════════════════════════════════════════════════════════════════════
# H11: MIPS Quality Measures
# ═══════════════════════════════════════════════════════════════════════════

class TestMIPS:
    def test_add_quality_measure(self, conn, env):
        result = _add_measure(conn, env, measure_id="MIPS-236", name="Controlling High Blood Pressure",
                              category="quality", benchmark="70",
                              numerator_criteria="Patients with BP < 140/90",
                              denominator_criteria="All hypertensive patients")
        assert is_ok(result), result
        assert "id" in result
        assert result["measure_id"] == "MIPS-236"
        assert result["name"] == "Controlling High Blood Pressure"
        assert result["category"] == "quality"
        assert result["measure_status"] == "active"

    def test_add_quality_measure_invalid_category(self, conn, env):
        result = _add_measure(conn, env, measure_id="BAD-001", name="Bad Measure",
                              category="invalid_category")
        assert is_error(result)

    def test_list_quality_measures(self, conn, env):
        _add_measure(conn, env, measure_id="MIPS-001", name="Measure A", category="quality")
        _add_measure(conn, env, measure_id="MIPS-002", name="Measure B", category="cost")
        _add_measure(conn, env, measure_id="MIPS-003", name="Measure C", category="quality")

        # List all
        result = call_action(mod.health_list_quality_measures, conn, ns(
            company_id=env["company_id"],
            category=None,
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["total_count"] >= 3

        # List by category
        result2 = call_action(mod.health_list_quality_measures, conn, ns(
            company_id=env["company_id"],
            category="quality",
            status=None,
            limit=50, offset=0,
        ))
        assert is_ok(result2), result2
        assert result2["total_count"] >= 2
        for row in result2["rows"]:
            assert row["category"] == "quality"

    def test_calculate_measure_result(self, conn, env):
        m = _add_measure(conn, env, measure_id="MIPS-236", name="BP Control",
                         category="quality", benchmark="70")
        assert is_ok(m)

        result = call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m["id"],
            reporting_period="2026-Q1",
            provider_id=env["provider_id"],
            numerator="85",
            denominator="100",
            exclusions="0",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["numerator"] == 85
        assert result["denominator"] == 100
        assert result["exclusions"] == 0
        assert result["effective_denominator"] == 100
        assert result["performance_rate"] == "85.00"
        assert result["result_status"] == "calculated"
        # 85% >= 70% benchmark -> full points
        assert result["points_earned"] == "10.00"

    def test_calculate_measure_result_with_exclusions(self, conn, env):
        m = _add_measure(conn, env, measure_id="MIPS-400", name="Exclusion Test",
                         category="quality", benchmark="80")
        assert is_ok(m)

        result = call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m["id"],
            reporting_period="2026-Q1",
            provider_id=None,
            numerator="60",
            denominator="100",
            exclusions="20",
            notes=None,
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["effective_denominator"] == 80
        # 60/80 = 75%
        assert result["performance_rate"] == "75.00"
        # 75% >= 80% * 0.5 = 40%, so partial points
        assert result["points_earned"] == "5.00"

    def test_mips_performance_dashboard(self, conn, env):
        # Create 2 measures and calculate results
        m1 = _add_measure(conn, env, measure_id="DASH-001", name="Dashboard Measure A",
                          category="quality", benchmark="70")
        assert is_ok(m1)
        m2 = _add_measure(conn, env, measure_id="DASH-002", name="Dashboard Measure B",
                          category="improvement_activities", benchmark="60")
        assert is_ok(m2)

        # Calculate result for m1
        call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m1["id"],
            reporting_period="2026-Q1",
            provider_id=None,
            numerator="90",
            denominator="100",
            exclusions="0",
            notes=None,
            limit=50, offset=0,
        ))

        # Calculate result for m2
        call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m2["id"],
            reporting_period="2026-Q1",
            provider_id=None,
            numerator="65",
            denominator="100",
            exclusions="0",
            notes=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_mips_performance_dashboard, conn, ns(
            company_id=env["company_id"],
            reporting_period="2026-Q1",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["measure_count"] >= 2
        assert len(result["measures"]) >= 2
        from decimal import Decimal
        assert Decimal(result["total_points_earned"]) >= Decimal("10")
        assert Decimal(result["composite_score"]) > Decimal("0")

        # Verify each measure has latest_result populated
        for m in result["measures"]:
            if m["measure_id"] in ("DASH-001", "DASH-002"):
                assert m["latest_result"] is not None

    def test_mips_submission_report(self, conn, env):
        m1 = _add_measure(conn, env, measure_id="SUB-001", name="Submission Measure A",
                          category="quality", benchmark="70")
        assert is_ok(m1)
        m2 = _add_measure(conn, env, measure_id="SUB-002", name="Submission Measure B",
                          category="cost", benchmark="50")
        assert is_ok(m2)

        # Calculate both
        call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m1["id"],
            reporting_period="2026-Q1",
            provider_id=None,
            numerator="80",
            denominator="100",
            exclusions="0",
            notes=None,
            limit=50, offset=0,
        ))
        call_action(mod.health_calculate_measure_result, conn, ns(
            measure_id=m2["id"],
            reporting_period="2026-Q1",
            provider_id=None,
            numerator="55",
            denominator="100",
            exclusions="0",
            notes=None,
            limit=50, offset=0,
        ))

        result = call_action(mod.health_mips_submission_report, conn, ns(
            company_id=env["company_id"],
            reporting_period="2026-Q1",
            limit=50, offset=0,
        ))
        assert is_ok(result), result
        assert result["reporting_period"] == "2026-Q1"
        assert result["total_measures"] >= 2
        assert result["calculated_count"] >= 2
        from decimal import Decimal
        assert Decimal(result["total_points_earned"]) >= Decimal("10")

        # Verify each submission item has expected fields
        for item in result["measures"]:
            assert "measure_id" in item
            assert "measure_name" in item
            assert "performance_rate" in item
            assert "points_earned" in item
            assert "result_status" in item
