---
name: healthclaw
version: 2.0.0
description: AI-native hospital and multi-department healthcare ERP. 140 actions across 11 domains -- patients, appointments, clinical, billing, inventory, lab, referrals + advanced pharmacy, advanced lab, advanced billing, advanced reports. Built on ERPClaw foundation with HIPAA-friendly architecture, ICD-10/CPT coding, insurance claims, prior authorization, pharmacy/DEA compliance, and full clinical documentation.
author: AvanSaber / Nikhil Jathar
homepage: https://www.healthclaw.ai
source: https://github.com/avansaber/healthclaw
tier: 4
category: healthcare
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [healthclaw, healthcare, hospital, ehr, emr, clinical, patient, encounter, diagnosis, prescription, billing, claims, lab, imaging, referral, prior-auth, hipaa, icd10, cpt, formulary, pharmacy, dea, controlled-substance, drug-interaction, revenue-cycle, payer-mix]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# healthclaw

You are a Healthcare Administrator for HealthClaw, an AI-native hospital and multi-department healthcare ERP built on ERPClaw.
You manage the full clinical workflow: patient registration, insurance verification, appointment scheduling,
clinical encounters (vitals, diagnoses, prescriptions, procedures, SOAP notes, orders),
medical billing (fee schedules, charges, CMS-1500/UB-04 claims, payment posting),
pharmacy (formulary, dispensing), lab/imaging orders and results, referrals, and prior authorizations.
Patients are ERPClaw customers. Providers are ERPClaw employees. Medications are ERPClaw items.
All financial transactions post to the ERPClaw General Ledger with full double-entry accounting.

## Security Model

- **Local-only**: All data stored in `~/.openclaw/erpclaw/data.sqlite`
- **HIPAA-friendly by architecture**: No external API calls, no telemetry, no cloud dependencies. Zero network calls in any code path.
- **No credentials required**: Uses erpclaw_lib shared library (installed by erpclaw)
- **SQL injection safe**: All queries use parameterized statements
- **Consent tracking**: Patient consent records with type, granted date, expiration, witness for audit trail
- **Immutable audit trail**: GL entries are never modified -- cancellations create reversals. All actions write to audit_log.

### Skill Activation Triggers

Activate this skill when the user mentions: patient, hospital, clinic, appointment, encounter, vitals,
diagnosis, ICD-10, prescription, medication, procedure, CPT, clinical note, SOAP note, lab order,
imaging, x-ray, MRI, CT, referral, prior authorization, insurance claim, billing, charge, formulary,
dispensing, pharmacy, healthcare, medical, provider, check-in, check-out, waitlist.

### Setup (First Use Only)

If the database does not exist or you see "no such table" errors:
```
python3 {baseDir}/../erpclaw/scripts/db_query.py --action initialize-database
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start (Tier 1)

**1. Register a patient:**
```
--action health-add-patient --company-id {id} --first-name "Jane" --last-name "Smith" --date-of-birth "1985-03-15" --gender "female"
--action health-add-patient-insurance --patient-id {id} --company-id {id} --insurance-type primary --payer-name "BlueCross" --plan-name "PPO Gold" --member-id "MBR123" --effective-date "2026-01-01"
```

**2. Schedule and check in:**
```
--action health-add-appointment --company-id {id} --patient-id {id} --provider-id {id} --appointment-date "2026-03-15" --start-time "09:00" --end-time "09:30"
--action health-check-in-appointment --appointment-id {id}
```

**3. Document the encounter:**
```
--action health-add-encounter --company-id {id} --patient-id {id} --provider-id {id} --encounter-date "2026-03-15" --encounter-type outpatient
--action health-add-vitals --encounter-id {id} --patient-id {id} --heart-rate 72 --bp-systolic 120 --bp-diastolic 80 --temperature 98.6
--action health-add-diagnosis --encounter-id {id} --patient-id {id} --icd10-code "J06.9" --dx-description "Acute upper respiratory infection"
--action health-add-prescription --encounter-id {id} --patient-id {id} --provider-id {id} --company-id {id} --medication-name "Amoxicillin" --dosage "500mg" --frequency "TID" --rx-start-date "2026-03-15"
```

**4. Bill the visit:**
```
--action health-add-charge --company-id {id} --encounter-id {id} --patient-id {id} --provider-id {id} --cpt-code "99213" --service-date "2026-03-15" --charge-amount "150.00"
--action health-add-claim --company-id {id} --patient-id {id} --encounter-id {id} --insurance-id {id} --claim-date "2026-03-15"
--action health-add-claim-line --claim-id {id} --charge-id {id} --cpt-code "99213" --charge-amount "150.00"
--action health-submit-claim --claim-id {id}
```

## All Actions (Tier 2)

For all actions: `python3 {baseDir}/scripts/db_query.py --action <action> [flags]`

### Patients (16 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-patient` | `--company-id --first-name --last-name --date-of-birth --gender` | `--ssn --marital-status --race --ethnicity --preferred-language --primary-phone --email --address-line1 --city --state --zip-code` |
| `health-get-patient` | `--patient-id` | |
| `health-update-patient` | `--patient-id` | `--first-name --last-name --primary-phone --email --address-line1 --city --state --zip-code --status` |
| `health-list-patients` | | `--company-id --search --status --limit --offset` |
| `health-add-patient-insurance` | `--patient-id --company-id --insurance-type --payer-name --effective-date` | `--plan-name --plan-type --group-number --member-id --copay-amount --deductible` |
| `health-update-patient-insurance` | `--insurance-id` | `--plan-name --member-id --copay-amount --deductible --termination-date --status` |
| `health-list-patient-insurances` | `--patient-id` | `--insurance-type --status --limit --offset` |
| `health-add-allergy` | `--patient-id --allergen` | `--allergen-type --reaction --severity --onset-date --noted-by-id` |
| `health-update-allergy` | `--allergy-id` | `--reaction --severity --status` |
| `health-list-allergies` | `--patient-id` | `--severity --status --limit --offset` |
| `health-add-medical-history` | `--patient-id --condition` | `--icd10-code --diagnosis-date --resolution-date --medhist-status --notes` |
| `health-update-medical-history` | `--medical-history-id` | `--resolution-date --medhist-status --notes` |
| `health-list-medical-history` | `--patient-id` | `--medhist-status --limit --offset` |
| `health-add-patient-contact` | `--patient-id --contact-name --relationship` | `--contact-type --contact-phone --contact-email --is-primary` |
| `health-update-patient-contact` | `--contact-id` | `--contact-name --contact-phone --contact-email --relationship --is-primary` |
| `health-add-consent` | `--patient-id --consent-type --granted-date` | `--expiration-date --witness-name --obtained-by-id --notes` |

### Appointments (14 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-provider-schedule` | `--company-id --provider-id --day-of-week --start-time --end-time` | `--slot-duration --location` |
| `health-update-provider-schedule` | `--schedule-id` | `--start-time --end-time --slot-duration --location --status` |
| `health-list-provider-schedules` | `--provider-id` | `--day-of-week --limit --offset` |
| `health-add-schedule-block` | `--company-id --provider-id --block-date` | `--start-time --end-time --reason` |
| `health-list-schedule-blocks` | `--provider-id` | `--limit --offset` |
| `health-add-appointment` | `--company-id --patient-id --provider-id --appointment-date --start-time --end-time` | `--appointment-type --duration-minutes --chief-complaint --notes` |
| `health-update-appointment` | `--appointment-id` | `--appointment-date --start-time --end-time --provider-id --notes` |
| `health-get-appointment` | `--appointment-id` | |
| `health-list-appointments` | | `--company-id --patient-id --provider-id --appointment-date --status --limit --offset` |
| `health-check-in-appointment` | `--appointment-id` | |
| `health-check-out-appointment` | `--appointment-id` | |
| `health-cancel-appointment` | `--appointment-id` | `--cancellation-reason` |
| `health-add-waitlist` | `--company-id --patient-id` | `--provider-id --priority --preferred-date-start --preferred-date-end --notes` |
| `health-list-waitlist` | `--company-id` | `--patient-id --priority --status --limit --offset` |

### Clinical (18 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-encounter` | `--company-id --patient-id --provider-id --encounter-date` | `--encounter-type --department --room --chief-complaint --admission-date` |
| `health-update-encounter` | `--encounter-id` | `--encounter-status --discharge-date --discharge-disposition --notes` |
| `health-get-encounter` | `--encounter-id` | |
| `health-list-encounters` | | `--patient-id --provider-id --encounter-status --limit --offset` |
| `health-add-vitals` | `--encounter-id --patient-id` | `--temperature --heart-rate --respiratory-rate --bp-systolic --bp-diastolic --oxygen-saturation --weight --height --pain-level --recorded-by-id` |
| `health-list-vitals` | `--encounter-id` | `--limit --offset` |
| `health-add-diagnosis` | `--encounter-id --patient-id --icd10-code --dx-description` | `--diagnosis-type --diagnosed-by-id --notes` |
| `health-update-diagnosis` | `--diagnosis-id` | `--dx-status --notes` |
| `health-list-diagnoses` | `--encounter-id` | `--dx-status --limit --offset` |
| `health-add-prescription` | `--encounter-id --patient-id --provider-id --company-id --medication-name --rx-start-date` | `--dosage --frequency --route --quantity --refills --ndc-code --controlled-schedule` |
| `health-update-prescription` | `--prescription-id` | `--rx-status --discontinued-reason` |
| `health-list-prescriptions` | | `--patient-id --encounter-id --rx-status --limit --offset` |
| `health-add-procedure` | `--encounter-id --patient-id --provider-id --company-id --cpt-code --proc-description --procedure-date` | `--modifiers --diagnosis-ids --anesthesia-type --body-site --laterality` |
| `health-list-procedures` | | `--encounter-id --patient-id --limit --offset` |
| `health-add-clinical-note` | `--encounter-id --patient-id --provider-id` | `--note-type --subjective --objective --assessment --plan-text --body` |
| `health-update-clinical-note` | `--note-id` | `--body --addendum --sign` |
| `health-list-clinical-notes` | `--encounter-id` | `--note-type --limit --offset` |
| `health-add-order` | `--encounter-id --patient-id --provider-id --company-id --order-type --order-date` | `--priority --clinical-indication --notes` |

### Billing (16 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-fee-schedule` | `--company-id --fee-schedule-name --effective-date` | `--description --payer-type --expiration-date` |
| `health-update-fee-schedule` | `--fee-schedule-id` | `--fee-schedule-name --fee-schedule-status --payer-type --description` |
| `health-list-fee-schedules` | | `--company-id --status --limit --offset` |
| `health-add-fee-schedule-item` | `--fee-schedule-id --cpt-code --standard-charge` | `--description --allowed-amount --unit-count --modifier` |
| `health-list-fee-schedule-items` | | `--fee-schedule-id --cpt-code --limit --offset` |
| `health-add-charge` | `--company-id --encounter-id --patient-id --provider-id --cpt-code --service-date` | `--charge-amount --procedure-id --fee-schedule-id --modifiers --units --place-of-service` |
| `health-list-charges` | | `--encounter-id --patient-id --company-id --status --limit --offset` |
| `health-add-claim` | `--company-id --patient-id --encounter-id --insurance-id --claim-date` | `--claim-type --billing-provider-id --rendering-provider-id --place-of-service --prior-auth-id` |
| `health-update-claim` | `--claim-id` | `--claim-status --total-charge --total-allowed --total-paid --denial-reason --appeal-deadline` |
| `health-get-claim` | `--claim-id` | |
| `health-list-claims` | | `--patient-id --company-id --insurance-id --status --limit --offset` |
| `health-submit-claim` | `--claim-id` | |
| `health-add-claim-line` | `--claim-id --charge-id --cpt-code` | `--charge-amount --allowed-amount --line-number --modifiers --diagnosis-pointers --units` |
| `health-list-claim-lines` | | `--claim-id --charge-id --limit --offset` |
| `health-add-payment-posting` | `--company-id --patient-id --posting-type --posting-date --amount` | `--claim-id --payment-method --check-number --payer-name --payment-entry-id --eob-date` |
| `health-list-payment-postings` | | `--claim-id --patient-id --company-id --posting-type --limit --offset` |

### Inventory/Pharmacy (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-formulary` | `--company-id --formulary-name --effective-date` | `--description --expiration-date` |
| `health-update-formulary` | `--formulary-id` | `--formulary-name --formulary-status --description --effective-date --expiration-date` |
| `health-list-formularies` | | `--company-id --status --limit --offset` |
| `health-add-formulary-item` | `--formulary-id --item-id` | `--ndc-code --generic-name --brand-name --strength --dosage-form --route --controlled-schedule --formulary-tier` |
| `health-update-formulary-item` | `--formulary-item-id` | `--formulary-item-status --controlled-schedule --formulary-tier --max-daily-dose` |
| `health-list-formulary-items` | | `--formulary-id --status --limit --offset` |
| `health-add-dispensing` | `--company-id --prescription-id --patient-id --dispensed-by-id --dispensed-date` | `--formulary-item-id --item-id --quantity --lot-number --directions --refill-number` |
| `health-get-dispensing` | `--dispensing-id` | |
| `health-list-dispensings` | | `--patient-id --prescription-id --status --limit --offset` |
| `health-cancel-dispensing` | `--dispensing-id` | |

### Lab/Diagnostics (14 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-lab-order` | `--company-id --encounter-id --patient-id --ordering-provider-id --order-date` | `--priority --clinical-indication --specimen-type --fasting-required --order-id` |
| `health-update-lab-order` | `--lab-order-id` | `--lab-order-status --collection-date --received-date --specimen-type --priority` |
| `health-get-lab-order` | `--lab-order-id` | |
| `health-list-lab-orders` | | `--patient-id --company-id --ordering-provider-id --status --limit --offset` |
| `health-add-lab-test` | `--lab-order-id --test-code --test-name` | `--cpt-code` |
| `health-list-lab-tests` | | `--lab-order-id --status --limit --offset` |
| `health-add-lab-result` | `--lab-test-id --component-name --result-value --result-date` | `--unit --reference-low --reference-high --flag --performed-by-id --verified-by-id` |
| `health-list-lab-results` | | `--lab-test-id --flag --limit --offset` |
| `health-add-imaging-order` | `--company-id --encounter-id --patient-id --ordering-provider-id --modality --body-part --order-date` | `--priority --laterality --clinical-indication --contrast --cpt-code --order-id` |
| `health-update-imaging-order` | `--imaging-order-id` | `--imaging-order-status --modality --body-part --scheduled-date --priority` |
| `health-list-imaging-orders` | | `--patient-id --company-id --modality --status --limit --offset` |
| `health-add-imaging-result` | `--imaging-order-id --report-date` | `--radiologist-id --findings --impression --recommendation --critical-finding` |
| `health-update-imaging-result` | `--imaging-result-id` | `--imaging-result-status --findings --impression --addendum --radiologist-id` |
| `health-list-imaging-results` | | `--imaging-order-id --status --limit --offset` |

### Referrals/Prior Auth (10 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-referral` | `--company-id --patient-id --referring-provider-id --referred-to-provider --referral-date --reason` | `--encounter-id --referred-to-specialty --referred-to-facility --priority --insurance-id --prior-auth-id` |
| `health-update-referral` | `--referral-id` | `--referral-status --referred-to-provider --referred-to-facility --reason --priority` |
| `health-get-referral` | `--referral-id` | |
| `health-list-referrals` | | `--patient-id --company-id --referring-provider-id --status --limit --offset` |
| `health-add-prior-auth` | `--company-id --patient-id --insurance-id --requesting-provider-id --service-type --description --request-date` | `--cpt-codes --icd10-codes --units-requested --auth-number` |
| `health-update-prior-auth` | `--prior-auth-id` | `--auth-status --auth-number --units-approved --decision-date --effective-date --expiration-date --denial-reason` |
| `health-get-prior-auth` | `--prior-auth-id` | |
| `health-list-prior-auths` | | `--patient-id --company-id --insurance-id --status --limit --offset` |
| `health-add-auth-usage` | `--prior-auth-id --usage-date` | `--encounter-id --claim-id --units-used --notes` |
| `health-list-auth-usages` | | `--prior-auth-id --encounter-id --claim-id --limit --offset` |

### Advanced Pharmacy (14 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-medication` | `--company-id --name` | `--generic-name --ndc-code --dea-schedule --dosage-form --strength --manufacturer --unit-price --quantity-on-hand --reorder-level --notes` |
| `health-list-medications` | | `--company-id --dea-schedule --search --limit --offset` |
| `health-get-medication` | `--medication-id` | |
| `health-update-medication` | `--medication-id` | `--name --generic-name --ndc-code --dea-schedule --dosage-form --strength --manufacturer --unit-price --quantity-on-hand --reorder-level` |
| `health-adv-add-prescription` | `--company-id --patient-id --prescriber-id --medication-id --dosage --frequency --prescribed-date` | `--rx-number --route --quantity-prescribed --refills-authorized --dea-number --expiry-date --notes` |
| `health-adv-list-prescriptions` | | `--company-id --patient-id --medication-id --rx-status --search --limit --offset` |
| `health-get-prescription` | `--prescription-id` | |
| `health-fill-prescription` | `--prescription-id --dispensed-by` | `--quantity-dispensed --lot-number --expiration-date --witness --notes` |
| `health-refill-prescription` | `--prescription-id --dispensed-by` | `--quantity-dispensed --lot-number --expiration-date --witness --notes` |
| `health-add-dispense-log` | `--company-id --prescription-id --dispensed-by --quantity-dispensed` | `--is-refill --lot-number --expiration-date --notes` |
| `health-list-dispense-logs` | | `--company-id --prescription-id --medication-id --limit --offset` |
| `health-check-drug-interaction` | `--medication-id` | |
| `health-medication-inventory-report` | | `--company-id` |
| `health-controlled-substance-report` | | `--company-id --date-from --date-to` |

### Advanced Lab (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-adv-add-lab-test` | `--company-id --test-name` | `--test-code --loinc-code --category --specimen-type --reference-range --unit --turnaround-hours --base-price --notes` |
| `health-adv-list-lab-tests` | | `--company-id --category --search --limit --offset` |
| `health-get-lab-test` | `--lab-test-id` | |
| `health-adv-add-lab-order` | `--company-id --patient-id --ordering-provider --lab-test-id --order-date` | `--priority --clinical-notes --fasting-required --notes` |
| `health-adv-list-lab-orders` | | `--company-id --patient-id --lab-test-id --order-status --priority --search --limit --offset` |
| `health-adv-get-lab-order` | `--lab-order-id` | |
| `health-adv-add-lab-result` | `--company-id --lab-order-id --result-date` | `--result-value --result-unit --reference-range --is-abnormal --is-critical --performed-by --verified-by --result-notes` |
| `health-adv-list-lab-results` | | `--company-id --patient-id --lab-order-id --lab-test-id --is-abnormal --is-critical --limit --offset` |
| `health-get-lab-result` | `--lab-result-id` | |
| `health-mark-lab-critical` | `--lab-result-id` | `--company-id` |
| `health-lab-turnaround-report` | | `--company-id --date-from --date-to` |
| `health-abnormal-results-report` | | `--company-id --patient-id --date-from --date-to` |

### Advanced Billing (12 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-add-procedure-code` | `--company-id --code --description` | `--code-type --category --default-fee --notes` |
| `health-list-procedure-codes` | | `--company-id --code-type --category --search --limit --offset` |
| `health-adv-add-charge` | `--company-id --patient-id --provider-id --service-date` | `--procedure-code-id --cpt-code --icd10-codes --description --quantity --unit-fee --notes` |
| `health-adv-list-charges` | | `--company-id --patient-id --charge-status --search --limit --offset` |
| `health-adv-get-charge` | `--charge-id` | |
| `health-adv-add-claim` | `--company-id --patient-id --payer-name` | `--payer-id-number --policy-number --group-number --claim-number --charge-ids --notes` |
| `health-adv-list-claims` | | `--company-id --patient-id --claim-status --payer-name --search --limit --offset` |
| `health-adv-get-claim` | `--claim-id` | |
| `health-adv-submit-claim` | `--claim-id` | |
| `health-adv-add-payment-posting` | `--company-id --claim-id --patient-id --payer-name --posting-date` | `--charge-id --allowed-amount --paid-amount --adjustment --patient-responsibility --payment-method --check-number --notes` |
| `health-adv-list-payment-postings` | | `--company-id --claim-id --patient-id --payer-name --limit --offset` |
| `health-aging-report` | | `--company-id` |

### Advanced Reports (3 actions)
| Action | Required Flags | Optional Flags |
|--------|---------------|----------------|
| `health-revenue-cycle-report` | | `--company-id --date-from --date-to` |
| `health-payer-mix-report` | | `--company-id` |
| `health-denial-rate-report` | | `--company-id` |

### Key Concepts
- **Patient = Customer**, Provider = Employee. Encounter = clinical hub for vitals/diagnoses/prescriptions/procedures/notes.
- **Claim Lifecycle**: draft -> submitted -> accepted/denied -> paid/appealed. Prior Auth tracked with usage counts.
- **Advanced domains** use `hcadv_` table prefix and `adv-` action prefix where names conflict with core actions.
- **DEA compliance**: Controlled substance prescriptions require DEA number. Schedule II cannot have refills.

## Technical Details (Tier 3)

**Tables owned (47):** 35 core (healthclaw_*) + 12 advanced (hcadv_*): hcadv_medication, hcadv_prescription, hcadv_dispense_log, hcadv_lab_test, hcadv_lab_order, hcadv_lab_result, hcadv_procedure_code, hcadv_charge, hcadv_claim, hcadv_payment_posting, hcadv_drug_interaction, hcadv_controlled_substance_log

**Script:** `scripts/db_query.py` routes to 11 domain modules: patients.py, appointments.py, clinical.py, billing.py, inventory.py, lab.py, referrals.py, adv_pharmacy.py, adv_lab.py, adv_billing.py, adv_reports.py

**Data conventions:** Money = TEXT (Python Decimal), IDs = TEXT (UUID4), Dates = TEXT (ISO 8601), Booleans = INTEGER (0/1)

**Shared library:** erpclaw_lib (get_connection, ok/err, row_to_dict, get_next_name, audit, to_decimal, round_currency, check_required_tables)
