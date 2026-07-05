# Changelog

All notable changes to the HealthClaw skill.

## [Unreleased] — M33 feature-completion (B11)

### Fixed
- **`health-check-drug-interaction` no longer returns a false safety clearance
  when no reference data is loaded (B11-SAFETY).** Previously an empty
  `healthclaw_drug_interaction` table produced `{"interaction_count": 0,
  "interactions": []}` — an authoritative-looking "no interactions found" that
  actually meant "no reference data loaded" (a clinical false-negative). The
  check now returns the module's `not_configured` shape (with
  `reference_pair_count: 0`) until interaction pairs are configured for the
  company, and returns `feature_status: "active"` with a `scope_note` +
  `reference_pair_count` when pairs exist, distinguishing "reference empty" from
  "genuinely no interaction for this medication." **Both the honesty count and
  the interaction match query are company-scoped** (`WHERE company_id = ?`,
  resolved from the checked medication's owning company), so one clinic's
  interaction data can never flip another clinic's result from not-configured to
  a false clean (BDFL checkpoint-① condition 2).

### Added
- **`health-add-drug-interaction` / `health-list-drug-interactions` (B11).**
  Bring-your-own reference-pair writers for `healthclaw_drug_interaction`
  (previously a reader-without-writer orphan). `add` validates the severity
  enum (`minor|moderate|major|contraindicated`), refuses a self-pair, and
  requires both medications to exist AND belong to the same company (no
  cross-company references). A built-in authoritative clinical dataset stays a
  deferred, founder-visible item.
- **`health-add-scheduling-rule` / `health-list-scheduling-rules` (B11).** Write
  path for `healthclaw_scheduling_rule`, making the documented "configure online
  scheduling rules" claim true. `health-online-scheduling-rules` continues to
  return stored rules, falling back to sensible defaults only when none are set.
