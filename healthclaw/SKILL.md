---
name: healthclaw
version: 2.0.0
description: AI-native healthcare ERP. 230 actions across 15 domains -- patients, appointments, clinical, billing, inventory, lab, referrals, advanced pharmacy, advanced lab, advanced billing, advanced reports, RCM, compliance, provider management, reports v2. HIPAA-friendly, ICD-10/CPT, insurance claims, prior auth, pharmacy/DEA, revenue cycle management.
author: AvanSaber
homepage: https://github.com/avansaber/healthclaw
source: https://github.com/avansaber/healthclaw
tier: 4
category: healthcare
requires: [erpclaw]
database: ~/.openclaw/erpclaw/data.sqlite
user-invocable: true
tags: [healthclaw, healthcare, hospital, ehr, emr, clinical, patient, encounter, diagnosis, prescription, billing, claims, lab, imaging, referral, prior-auth, hipaa, icd10, cpt, formulary, pharmacy, dea, controlled-substance, drug-interaction, revenue-cycle, payer-mix, rcm, compliance, provider, credentialing, fhir]
scripts:
  - scripts/db_query.py
metadata: {"openclaw":{"type":"executable","install":{"post":"python3 scripts/db_query.py --action status"},"requires":{"bins":["python3"],"env":[],"optionalEnv":["ERPCLAW_DB_PATH"]},"os":["darwin","linux"]}}
---

# healthclaw

Healthcare Administrator for HealthClaw -- AI-native hospital/clinic ERP on ERPClaw.
Manages patients, appointments, encounters, vitals, diagnoses, prescriptions, procedures, SOAP notes,
billing (fee schedules, charges, CMS-1500/UB-04 claims), pharmacy (formulary, dispensing, DEA),
lab/imaging, referrals, prior auth, RCM, compliance (HIPAA, BAA), and provider credentialing.
All financials post to ERPClaw GL with double-entry accounting. Zero network calls.

### Skill Activation Triggers

Activate when user mentions: patient, hospital, clinic, appointment, encounter, vitals,
diagnosis, ICD-10, prescription, medication, procedure, CPT, clinical note, SOAP note, lab order,
imaging, x-ray, MRI, referral, prior authorization, insurance claim, billing, charge, formulary,
dispensing, pharmacy, healthcare, medical, provider, check-in, check-out, waitlist, FHIR, payer,
revenue cycle, credentialing, BAA, HIPAA, breach, PHI.

### Setup
```
python3 {baseDir}/../erpclaw/scripts/db_query.py --action initialize-database
python3 {baseDir}/scripts/db_query.py --action status
```

## Quick Start

```
--action health-add-patient --company-id {id} --first-name "Jane" --last-name "Smith" --date-of-birth "1985-03-15" --gender "female"
--action health-add-appointment --company-id {id} --patient-id {id} --provider-id {id} --appointment-date "2026-03-15" --start-time "09:00" --end-time "09:30"
--action health-check-in-appointment --appointment-id {id}
--action health-add-encounter --company-id {id} --patient-id {id} --provider-id {id} --encounter-date "2026-03-15"
--action health-add-vitals --encounter-id {id} --patient-id {id} --heart-rate 72 --bp-systolic 120 --bp-diastolic 80
--action health-add-charge --company-id {id} --encounter-id {id} --patient-id {id} --provider-id {id} --cpt-code "99213" --service-date "2026-03-15" --charge-amount "150.00"
--action health-submit-claim --claim-id {id}
```

## All 230 Actions

| Action | Description |
|--------|-------------|
| `health-add-patient` | Register new patient with demographics |
| `health-get-patient` | Get patient record |
| `health-update-patient` | Update patient demographics |
| `health-list-patients` | List/search patients |
| `health-merge-patients` | Merge duplicate patient records |
| `health-add-patient-insurance` | Add insurance coverage to patient |
| `health-update-patient-insurance` | Update insurance details |
| `health-list-patient-insurances` | List patient insurance policies |
| `health-add-allergy` | Record patient allergy |
| `health-update-allergy` | Update allergy severity/status |
| `health-list-allergies` | List patient allergies |
| `health-add-medical-history` | Add past medical condition |
| `health-update-medical-history` | Update medical history entry |
| `health-list-medical-history` | List medical history |
| `health-add-patient-contact` | Add emergency/next-of-kin contact |
| `health-update-patient-contact` | Update patient contact |
| `health-add-consent` | Record patient consent |
| `health-add-consent-template` | Create reusable consent template |
| `health-list-consent-templates` | List consent templates |
| `health-add-patient-education` | Assign patient education material |
| `health-list-patient-education` | List patient education records |
| `health-fhir-export-patient` | Export patient in FHIR format |
| `health-add-provider-schedule` | Set provider availability |
| `health-update-provider-schedule` | Update provider schedule |
| `health-list-provider-schedules` | List provider schedules |
| `health-add-schedule-block` | Block provider time slot |
| `health-list-schedule-blocks` | List schedule blocks |
| `health-add-appointment` | Schedule patient appointment |
| `health-update-appointment` | Reschedule appointment |
| `health-get-appointment` | Get appointment details |
| `health-list-appointments` | List/filter appointments |
| `health-check-in-appointment` | Check in patient for appointment |
| `health-check-out-appointment` | Check out patient |
| `health-cancel-appointment` | Cancel appointment |
| `health-add-waitlist` | Add patient to waitlist |
| `health-list-waitlist` | List waitlisted patients |
| `health-check-room-availability` | Check room availability |
| `health-create-recurring-appointment` | Create recurring appointment series |
| `health-list-recurring-series` | List recurring appointment series |
| `health-schedule-multi-resource` | Schedule multi-resource appointment |
| `health-online-scheduling-rules` | Configure online scheduling rules |
| `health-add-reminder` | Add appointment reminder |
| `health-list-reminders` | List reminders |
| `health-process-reminders` | Process pending reminders |
| `health-add-encounter` | Create clinical encounter |
| `health-update-encounter` | Update encounter status/details |
| `health-get-encounter` | Get encounter with all data |
| `health-list-encounters` | List encounters |
| `health-add-vitals` | Record vital signs |
| `health-list-vitals` | List vitals for encounter |
| `health-add-diagnosis` | Add ICD-10 diagnosis |
| `health-update-diagnosis` | Update diagnosis status |
| `health-list-diagnoses` | List diagnoses |
| `health-add-prescription` | Write prescription |
| `health-update-prescription` | Update prescription status |
| `health-get-prescription` | Get prescription details |
| `health-list-prescriptions` | List prescriptions |
| `health-add-procedure` | Record clinical procedure |
| `health-list-procedures` | List procedures |
| `health-add-clinical-note` | Add SOAP/progress note |
| `health-update-clinical-note` | Update/sign clinical note |
| `health-list-clinical-notes` | List clinical notes |
| `health-add-order` | Create clinical order |
| `health-add-problem` | Add to problem list |
| `health-list-active-problems` | List active problems |
| `health-add-care-team-member` | Add care team member |
| `health-remove-care-team-member` | Remove care team member |
| `health-list-care-team` | List care team |
| `health-add-immunization` | Record immunization |
| `health-update-immunization` | Update immunization record |
| `health-get-immunization-record` | Get immunization details |
| `health-list-immunizations` | List immunizations |
| `health-add-med-reconciliation` | Start medication reconciliation |
| `health-get-med-reconciliation` | Get med reconciliation |
| `health-list-med-reconciliations` | List med reconciliations |
| `health-generate-ccd` | Generate Continuity of Care Document |
| `health-growth-chart` | Generate pediatric growth chart |
| `health-immunizations-due-report` | Report on immunizations due |
| `health-add-fee-schedule` | Create fee schedule |
| `health-update-fee-schedule` | Update fee schedule |
| `health-list-fee-schedules` | List fee schedules |
| `health-add-fee-schedule-item` | Add item to fee schedule |
| `health-list-fee-schedule-items` | List fee schedule items |
| `health-link-payer-fee-schedule` | Link payer to fee schedule |
| `health-add-charge` | Add billing charge |
| `health-list-charges` | List charges |
| `health-add-claim` | Create insurance claim |
| `health-update-claim` | Update claim status |
| `health-get-claim` | Get claim details |
| `health-list-claims` | List claims |
| `health-submit-claim` | Submit claim for processing |
| `health-add-claim-line` | Add line item to claim |
| `health-list-claim-lines` | List claim line items |
| `health-add-payment-posting` | Post payment to claim |
| `health-list-payment-postings` | List payment postings |
| `health-add-payment-plan` | Create patient payment plan |
| `health-list-payment-plans` | List payment plans |
| `health-record-plan-payment` | Record payment plan installment |
| `health-payment-plan-status` | Check payment plan status |
| `health-generate-patient-statement` | Generate patient statement |
| `health-list-patient-statements` | List patient statements |
| `health-generate-superbill` | Generate encounter superbill |
| `health-generate-good-faith-estimate` | Generate No Surprises Act estimate |
| `health-provide-good-faith-estimate` | Provide GFE to patient |
| `health-list-good-faith-estimates` | List good faith estimates |
| `health-add-formulary` | Create drug formulary |
| `health-update-formulary` | Update formulary |
| `health-list-formularies` | List formularies |
| `health-add-formulary-item` | Add drug to formulary |
| `health-update-formulary-item` | Update formulary item |
| `health-list-formulary-items` | List formulary items |
| `health-add-dispensing` | Dispense medication |
| `health-get-dispensing` | Get dispensing record |
| `health-list-dispensings` | List dispensings |
| `health-cancel-dispensing` | Cancel dispensing |
| `health-add-lab-order` | Create lab order |
| `health-update-lab-order` | Update lab order status |
| `health-get-lab-order` | Get lab order details |
| `health-list-lab-orders` | List lab orders |
| `health-add-lab-test` | Add test to lab order |
| `health-get-lab-test` | Get lab test details |
| `health-list-lab-tests` | List lab tests |
| `health-add-lab-result` | Record lab result |
| `health-get-lab-result` | Get lab result |
| `health-list-lab-results` | List lab results |
| `health-mark-lab-critical` | Mark lab result as critical |
| `health-add-imaging-order` | Create imaging order |
| `health-update-imaging-order` | Update imaging order |
| `health-list-imaging-orders` | List imaging orders |
| `health-add-imaging-result` | Record imaging result |
| `health-update-imaging-result` | Update imaging result |
| `health-list-imaging-results` | List imaging results |
| `health-add-referral` | Create patient referral |
| `health-update-referral` | Update referral status |
| `health-get-referral` | Get referral details |
| `health-list-referrals` | List referrals |
| `health-add-prior-auth` | Request prior authorization |
| `health-update-prior-auth` | Update prior auth decision |
| `health-get-prior-auth` | Get prior auth details |
| `health-list-prior-auths` | List prior authorizations |
| `health-add-auth-usage` | Record auth usage |
| `health-list-auth-usages` | List auth usages |
| `health-add-medication` | Add medication to catalog |
| `health-get-medication` | Get medication details |
| `health-update-medication` | Update medication |
| `health-list-medications` | List medications |
| `health-adv-add-prescription` | Create advanced prescription |
| `health-adv-list-prescriptions` | List advanced prescriptions |
| `health-fill-prescription` | Fill prescription (dispense) |
| `health-refill-prescription` | Refill prescription |
| `health-add-dispense-log` | Log dispensing event |
| `health-list-dispense-logs` | List dispense logs |
| `health-check-drug-interaction` | Check drug interactions |
| `health-adv-add-lab-test` | Add lab test to catalog |
| `health-adv-list-lab-tests` | List lab test catalog |
| `health-adv-add-lab-order` | Create advanced lab order |
| `health-adv-list-lab-orders` | List advanced lab orders |
| `health-adv-get-lab-order` | Get advanced lab order |
| `health-adv-add-lab-result` | Record advanced lab result |
| `health-adv-list-lab-results` | List advanced lab results |
| `health-add-procedure-code` | Add CPT/procedure code |
| `health-list-procedure-codes` | List procedure codes |
| `health-adv-add-charge` | Create advanced charge |
| `health-adv-list-charges` | List advanced charges |
| `health-adv-get-charge` | Get advanced charge |
| `health-adv-add-claim` | Create advanced claim |
| `health-adv-list-claims` | List advanced claims |
| `health-adv-get-claim` | Get advanced claim |
| `health-adv-submit-claim` | Submit advanced claim |
| `health-adv-add-payment-posting` | Post advanced payment |
| `health-adv-list-payment-postings` | List advanced postings |
| `health-scrub-claim` | Pre-submission claim scrubbing |
| `health-batch-submit-claims` | Batch submit multiple claims |
| `health-record-denial` | Record claim denial |
| `health-list-denied-claims` | List denied claims |
| `health-submit-appeal` | Submit denial appeal |
| `health-resolve-appeal` | Resolve appeal outcome |
| `health-record-eligibility-check` | Record eligibility verification |
| `health-check-eligibility-status` | Check eligibility status |
| `health-list-eligibility-checks` | List eligibility checks |
| `health-get-latest-eligibility` | Get latest eligibility |
| `health-import-era-file` | Import ERA/835 file |
| `health-auto-post-era` | Auto-post ERA payments |
| `health-list-era-files` | List imported ERA files |
| `health-get-era-file-details` | Get ERA file details |
| `health-auto-crossover-claim` | Auto-create crossover claim |
| `health-list-crossover-claims` | List crossover claims |
| `health-add-payer` | Add insurance payer |
| `health-get-payer` | Get payer details |
| `health-update-payer` | Update payer info |
| `health-list-payers` | List payers |
| `health-add-payer-enrollment` | Add payer enrollment |
| `health-list-payer-enrollments` | List payer enrollments |
| `health-check-enrollment-revalidation` | Check enrollment revalidation |
| `health-add-provider-credential` | Add provider credential |
| `health-list-provider-credentials` | List provider credentials |
| `health-check-expiring-credentials` | Check expiring credentials |
| `health-add-quality-measure` | Add quality measure |
| `health-list-quality-measures` | List quality measures |
| `health-calculate-measure-result` | Calculate measure result |
| `health-add-baa` | Add Business Associate Agreement |
| `health-list-baas` | List BAAs |
| `health-check-expiring-baas` | Check expiring BAAs |
| `health-add-breach-incident` | Report HIPAA breach |
| `health-update-breach-incident` | Update breach incident |
| `health-list-breach-incidents` | List breach incidents |
| `health-log-phi-access` | Log PHI access event |
| `health-phi-access-report` | PHI access audit report |
| `health-phi-access-anomaly-check` | Detect PHI access anomalies |
| `health-revenue-cycle-report` | Revenue cycle dashboard |
| `health-payer-mix-report` | Payer mix analysis |
| `health-denial-rate-report` | Denial rate report |
| `health-aging-report` | AR aging report |
| `health-collections-aging-report` | Collections aging report |
| `health-charge-reconciliation-report` | Charge reconciliation |
| `health-denial-trend-report` | Denial trend analysis |
| `health-underpayment-report` | Underpayment detection |
| `health-payer-performance-report` | Payer performance metrics |
| `health-appeal-success-rate-report` | Appeal success rates |
| `health-era-reconciliation-report` | ERA reconciliation |
| `health-medication-inventory-report` | Medication inventory |
| `health-controlled-substance-report` | Controlled substance log |
| `health-lab-turnaround-report` | Lab turnaround times |
| `health-abnormal-results-report` | Abnormal lab results |
| `health-lab-interface-status` | Lab interface status |
| `health-provider-productivity-report` | Provider productivity |
| `health-provider-credential-report` | Provider credential status |
| `health-breach-summary-report` | HIPAA breach summary |
| `health-mips-performance-dashboard` | MIPS performance dashboard |
| `health-mips-submission-report` | MIPS submission report |

## Key Concepts
- **Patient = Customer**, Provider = Employee. Encounter = clinical hub for vitals/diagnoses/prescriptions/procedures/notes.
- **Claim Lifecycle**: draft -> submitted -> accepted/denied -> paid/appealed. Prior Auth tracked with usage counts.
- **DEA compliance**: Controlled substance prescriptions require DEA number. Schedule II cannot have refills.
- **Advanced domains** use `adv-` prefix where names conflict with core actions.

## Technical Details (Tier 3)
**Tables (40):** All use `healthclaw_` prefix. **Script:** `scripts/db_query.py` routes to 15 modules. **Data:** Money=TEXT(Decimal), IDs=TEXT(UUID4). **Lib:** erpclaw_lib.
