"""Audit rows name the table and the record (appointments, billing, clinical, patients)."""
import ast
import os
import uuid

from health_helpers import call_action, ns, is_ok, load_db_query

from erpclaw_lib.query import Field, P, Q, Table

mod = load_db_query()

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
MODULE_DIR = os.path.dirname(TESTS_DIR)

IN_SCOPE = ["appointments.py", "billing.py", "clinical.py", "patients.py"]
SKILL = "healthclaw"
TABLE_PREFIX = "healthclaw_"
ACTION_PREFIXES = ("health-", "dental-", "vet-", "mental-", "homehealth-")


def _audit_by_entity(conn, entity_id):
    t = Table("audit_log")
    sql = Q.from_(t).select(
        Field("skill"), Field("action"), Field("entity_type"),
        Field("entity_id"), Field("new_values"),
    ).where(Field("entity_id") == P()).get_sql()
    return [dict(r) for r in conn.execute(sql, (entity_id,)).fetchall()]


def test_every_audit_call_has_the_foundation_shape():
    for fname in IN_SCOPE:
        src = open(os.path.join(MODULE_DIR, fname)).read()
        tree = ast.parse(src)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else (
                    func.id if isinstance(func, ast.Name) else None)
                if name == "audit":
                    calls.append(node)
        assert len(calls) >= 1, fname
        for node in calls:
            assert len(node.args) >= 5, fname
            second = node.args[1]
            ok_skill = (
                (isinstance(second, ast.Name) and second.id == "SKILL")
                or (isinstance(second, ast.Constant)
                    and second.value == SKILL)
            )
            assert ok_skill, fname
            third = node.args[2]
            assert isinstance(third, ast.Constant) and isinstance(
                third.value, str), fname
            assert third.value.startswith(ACTION_PREFIXES), fname
            fourth = node.args[3]
            assert isinstance(fourth, ast.Constant) and isinstance(
                fourth.value, str), fname
            assert fourth.value.startswith(TABLE_PREFIX), fname
            assert fourth.value == fourth.value.lower(), fname
            assert "_" in fourth.value, fname


def test_appointments_audit_rows(conn, env):
    r1 = call_action(mod.health_add_appointment, conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], appointment_date="2026-03-25",
        start_time="14:00", end_time="14:30", duration_minutes="30",
        appointment_type="new_patient", chief_complaint=None, location=None,
        notes=None, cancellation_reason=None, new_provider_id=None,
        limit=50, offset=0, search=None, status=None,
    ))
    assert is_ok(r1), r1
    rows = _audit_by_entity(conn, r1["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-appointment", "healthclaw_appointment")

    upd_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO healthclaw_appointment "
        "(id, patient_id, provider_id, appointment_date, start_time, "
        "end_time, status, company_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (upd_id, env["patient_id"], env["provider_id"], "2026-03-26",
         "09:00", "09:30", "scheduled", env["company_id"]),
    )
    conn.commit()
    r2 = call_action(mod.health_update_appointment, conn, ns(
        appointment_id=upd_id, appointment_date=None, start_time=None,
        end_time=None, appointment_type=None, chief_complaint=None,
        location="Room 202", notes=None, cancellation_reason=None,
        duration_minutes=None, new_provider_id=None, limit=50, offset=0,
    ))
    assert is_ok(r2), r2
    rows = _audit_by_entity(conn, upd_id)
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-update-appointment", "healthclaw_appointment")

    ci_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO healthclaw_appointment "
        "(id, patient_id, provider_id, appointment_date, start_time, "
        "end_time, status, company_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (ci_id, env["patient_id"], env["provider_id"], "2026-03-27",
         "10:00", "10:30", "scheduled", env["company_id"]),
    )
    conn.commit()
    r3 = call_action(mod.health_check_in_appointment, conn, ns(
        appointment_id=ci_id, limit=50, offset=0,
    ))
    assert is_ok(r3), r3
    rows = _audit_by_entity(conn, ci_id)
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-check-in-appointment", "healthclaw_appointment")


def test_billing_audit_rows(conn, env):
    r1 = call_action(mod.health_add_fee_schedule, conn, ns(
        company_id=env["company_id"],
        fee_schedule_name="Standard Fee Schedule",
        description=None, effective_date="2026-01-01",
        expiration_date=None, fee_schedule_status=None, notes=None,
        payer_type=None, limit=50, offset=0,
    ))
    assert is_ok(r1), r1
    rows = _audit_by_entity(conn, r1["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-fee-schedule", "healthclaw_fee_schedule")

    fs2 = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO healthclaw_fee_schedule "
        "(id, name, effective_date, status, company_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (fs2, "Seeded Schedule", "2026-01-01", "active",
         env["company_id"]),
    )
    conn.commit()
    r2 = call_action(mod.health_update_fee_schedule, conn, ns(
        fee_schedule_id=fs2, fee_schedule_name=None,
        description="Updated description", fee_schedule_status=None,
        effective_date=None, expiration_date=None, notes=None,
        payer_type=None, limit=50, offset=0,
    ))
    assert is_ok(r2), r2
    rows = _audit_by_entity(conn, fs2)
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-update-fee-schedule", "healthclaw_fee_schedule")

    ins = call_action(mod.health_add_patient_insurance, conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        insurance_type="primary", payer_name="Acme Health", payer_id=None,
        plan_name=None, plan_type=None, group_number=None,
        member_id="MEM-AUDIT-1", subscriber_name=None, subscriber_dob=None,
        subscriber_relationship=None, copay_amount=None, deductible=None,
        deductible_met=None, out_of_pocket_max=None,
        effective_date="2026-01-01", termination_date=None,
        preauth_required=None, status=None,
    ))
    assert is_ok(ins), ins
    cl = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO healthclaw_claim "
        "(id, patient_id, insurance_id, encounter_id, claim_date, "
        "claim_status, company_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (cl, env["patient_id"], ins["id"], env["encounter_id"],
         "2026-03-20", "draft", env["company_id"]),
    )
    conn.commit()
    r3 = call_action(mod.health_record_denial, conn, ns(
        claim_id=cl, denial_category="CO", denial_code="45",
        denial_reason=None, denial_date=None,
    ))
    assert is_ok(r3), r3
    rows = _audit_by_entity(conn, cl)
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-record-denial", "healthclaw_claim")


def test_clinical_audit_rows(conn, env):
    r1 = call_action(mod.health_add_encounter, conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], encounter_date="2026-03-15",
        encounter_type="outpatient", encounter_status=None,
        department=None, room=None, appointment_id=None,
        admission_date=None, discharge_date=None,
        discharge_disposition=None, notes=None, status=None,
        limit=50, offset=0, search=None,
    ))
    assert is_ok(r1), r1
    rows = _audit_by_entity(conn, r1["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-encounter", "healthclaw_encounter")

    r2 = call_action(mod.health_update_encounter, conn, ns(
        encounter_id=env["encounter_id"], encounter_type=None,
        chief_complaint=None, department="Updated Dept", room=None,
        admission_date=None, discharge_date=None,
        discharge_disposition=None, notes=None,
        encounter_status="completed", limit=50, offset=0,
    ))
    assert is_ok(r2), r2
    rows = _audit_by_entity(conn, env["encounter_id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-update-encounter", "healthclaw_encounter")

    r3 = call_action(mod.health_add_diagnosis, conn, ns(
        encounter_id=env["encounter_id"], patient_id=env["patient_id"],
        icd10_code="J06.9", dx_description="Acute upper respiratory infection",
        diagnosis_type="primary", dx_status=None,
        diagnosed_by_id=env["provider_id"], notes=None,
        limit=50, offset=0,
    ))
    assert is_ok(r3), r3
    rows = _audit_by_entity(conn, r3["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-diagnosis", "healthclaw_diagnosis")


def test_patients_audit_rows(conn, env):
    r1 = call_action(mod.health_add_patient, conn, ns(
        company_id=env["company_id"], first_name="Alice",
        last_name="Johnson", date_of_birth="1985-03-15", gender="female",
        ssn=None, marital_status=None, race=None, ethnicity=None,
        preferred_language=None, primary_phone=None, secondary_phone=None,
        email=None, address_line1=None, address_line2=None, city=None,
        state=None, zip_code=None, primary_provider_id=None,
        customer_id=None, notes=None, limit=50, offset=0,
    ))
    assert is_ok(r1), r1
    rows = _audit_by_entity(conn, r1["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-patient", "healthclaw_patient")

    r2 = call_action(mod.health_update_patient, conn, ns(
        patient_id=env["patient_id"], first_name=None, last_name=None,
        date_of_birth=None, gender=None, ssn=None, marital_status=None,
        race=None, ethnicity=None, preferred_language=None,
        primary_phone=None, secondary_phone=None,
        email="updated@example.com", address_line1=None, address_line2=None,
        city=None, state=None, zip_code=None, primary_provider_id=None,
        status=None, notes=None, customer_id=None, limit=50, offset=0,
    ))
    assert is_ok(r2), r2
    rows = _audit_by_entity(conn, env["patient_id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-update-patient", "healthclaw_patient")

    r3 = call_action(mod.health_add_consent, conn, ns(
        patient_id=env["patient_id"], company_id=env["company_id"],
        consent_type="hipaa_privacy", description=None,
        granted_date="2026-01-15", expiration_date=None, witness_name=None,
        obtained_by_id=None, notes=None, limit=50, offset=0,
    ))
    assert is_ok(r3), r3
    rows = _audit_by_entity(conn, r3["id"])
    assert len(rows) == 1
    assert (rows[0]["skill"], rows[0]["action"],
            rows[0]["entity_type"]) == (
        "healthclaw", "health-add-consent", "healthclaw_consent")


def test_no_audit_row_is_keyed_by_company(conn, env):
    r1 = call_action(mod.health_add_patient, conn, ns(
        company_id=env["company_id"], first_name="NoKey",
        last_name="Check", date_of_birth="1990-01-01", gender="male",
        ssn=None, marital_status=None, race=None, ethnicity=None,
        preferred_language=None, primary_phone=None, secondary_phone=None,
        email=None, address_line1=None, address_line2=None, city=None,
        state=None, zip_code=None, primary_provider_id=None,
        customer_id=None, notes=None, limit=50, offset=0,
    ))
    assert is_ok(r1), r1
    r2 = call_action(mod.health_add_encounter, conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], encounter_date="2026-03-15",
        encounter_type="outpatient", encounter_status=None,
        department=None, room=None, appointment_id=None,
        admission_date=None, discharge_date=None,
        discharge_disposition=None, notes=None, status=None,
        limit=50, offset=0, search=None,
    ))
    assert is_ok(r2), r2
    r3 = call_action(mod.health_add_appointment, conn, ns(
        company_id=env["company_id"], patient_id=env["patient_id"],
        provider_id=env["provider_id"], appointment_date="2026-03-25",
        start_time="14:00", end_time="14:30", duration_minutes="30",
        appointment_type="new_patient", chief_complaint=None, location=None,
        notes=None, cancellation_reason=None, new_provider_id=None,
        limit=50, offset=0, search=None, status=None,
    ))
    assert is_ok(r3), r3
    r4 = call_action(mod.health_add_fee_schedule, conn, ns(
        company_id=env["company_id"],
        fee_schedule_name="Standard Fee Schedule",
        description=None, effective_date="2026-01-01",
        expiration_date=None, fee_schedule_status=None, notes=None,
        payer_type=None, limit=50, offset=0,
    ))
    assert is_ok(r4), r4
    t = Table("audit_log")
    sql = Q.from_(t).select(
        Field("skill"), Field("entity_id")).where(
        Field("skill") == P()).get_sql()
    scoped = [dict(r) for r in conn.execute(sql, ("healthclaw",)).fetchall()]
    assert scoped, "expected audit rows for healthclaw skill"
    for row in scoped:
        assert row["entity_id"] != env["company_id"]
    sql_all = Q.from_(t).select(Field("skill")).get_sql()
    skills = [r[0] for r in conn.execute(sql_all).fetchall()]
    assert skills
    for skill in skills:
        assert not skill.startswith(TABLE_PREFIX)
