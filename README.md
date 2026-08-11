# Frappe Scenario

Deterministic, AI-operable synthetic business data for Frappe and ERPNext.

Frappe Scenario turns a versioned JSON or YAML specification into a coherent,
owned dataset created through normal Frappe and ERPNext document APIs. A run can
be planned without writing data, generated synchronously or on a worker,
validated, exported, reproduced from the same seed, and cleaned up without
touching records owned by another run.

The first vertical slice models a Kuwait HVAC distributor. It creates company
and accounting foundations, locale-aware parties and addresses, a priced item
catalogue, opening stock, linked buying and selling lifecycles, invoices,
payments, and balanced ledger activity.

## Safety

Generation is intended for disposable development sites. The target site must
have both settings enabled:

```bash
bench set-config developer_mode 1
bench set-config frappe_scenario_disposable 1
```

Do not install or run this app on a production site. Cleanup only operates on
records and setting changes recorded in a run's private ownership manifest.

## Installation

The authoritative development checkout lives in the primary Bench:

```bash
cd /path/to/frappe-bench
bench get-app /path/to/frappe_scenario
bench install-app frappe_scenario
bench migrate
```

Frappe and ERPNext are managed by Bench. Faker, JSON Schema validation, and
YAML parsing are declared application dependencies.

ERPNext is a required app. When its checkout is already in the Bench,
`install-app frappe_scenario` installs ERPNext first if necessary. If the
checkout is absent, fetch it explicitly and retry; Frappe Scenario never fetches
repositories from an installation hook:

```bash
bench get-app erpnext
bench install-app erpnext
bench install-app frappe_scenario
```

Installation creates a resumable `Scenario Onboarding` record from a read-only
preflight. It does not prompt, initialize ERPNext, or generate business data.
The first System Manager who signs into Desk is routed once to the incomplete
onboarding record; other users and completed onboarding sessions are unaffected.

Continue onboarding in Desk at `/app/scenario-setup`, or use its CLI twin:

```bash
bench scenario setup
```

Both clients save the same validated choices and show proposed ERPNext setup
changes plus a dataset record estimate before asking for approval. Approved
plans initialize only missing ERPNext foundations through normal ERPNext
controllers; they do not generate scenario business data. For a
repeatable noninteractive preview and approval, pass a complete JSON object:

```bash
bench scenario setup --choices onboarding-choices.json --yes --json
```

Every changed pre-existing setting and its prior value is retained in the
onboarding bootstrap ownership manifest. Repeating setup is idempotent.

Purpose, dataset size, and operational depth are independent. Purpose records
whether the scenario is for learning, presentation, realistic business, AI
compilation, or testing. Scale controls the target record range and history.
Depth controls lifecycle coverage—how many orders progress to fulfillment,
invoicing, and payment. Existing `scenario-1.0` specifications remain valid;
missing purpose and depth default to `Quick Demo` and `Everyday Business`.

Party and catalog previews use a deterministic realism pipeline. Seeded Faker
provides name primitives, while the selected country pack and business
archetype provide legal forms, commercial vocabulary, address shape, telephone
format, product terminology, and price bands. Visibly synthetic or awkward
combinations are rejected before insertion, and all generated e-mail addresses
remain under reserved `.example` domains. “New sample variation” changes only
the preview variation; saving unchanged choices reproduces the same samples.

## Business archetypes

Scenario advertises only archetypes whose complete smoke lifecycle has passed
against real ERPNext controllers. The current catalogue is HVAC Distribution,
General Trading, Distribution and Wholesale, Retail, and Professional
Services. Each archetype declares its supported modules, regional vocabulary,
operational ratios, learning paths, validation expectations, and required
provider capabilities.

Manufacturing and Construction/Project Contracting already have declarative
vocabulary and acceptance contracts, but remain deliberately hidden and cannot
be selected until their optional operational providers pass the same lifecycle
gate. Capability discovery and AI compilation therefore cannot promise an
archetype that the generation engine does not yet support.

## Learn ERPNext

The learning experience uses normal generated ERPNext documents, Scenario
Events, progressive paths, evidence-backed explanations, safe checkpoints,
module resets, and troubleshooting labs. It does not replace ERPNext with a
simplified parallel model; lessons link directly to the relevant document or
report and cleanup remains limited to manifest-owned records.

The Selling path also includes a focused ten-step interactive **Order to cash**
tutorial. Launch it manually from the Learning page of a completed Scenario
Run. The runner follows scenario-bound Sales Order, Delivery Note, Sales
Invoice, and Payment Entry records across Desk routes, uses native Form Tours
for stable field guidance, and saves progress per learner and catalogue
version. Exiting never loses the current step; the floating **Resume tutorial**
button restores it. Completion is awarded only after the server verifies each
linked ERPNext document.

## Quick start

Scenario commands use the Bench default site configured by `bench use`.
Supply `--site <site-name>` before `scenario` to target another site explicitly.

For a polished, warning-free demonstration, choose **Presentation Demo** in
`bench scenario setup` or the Desk setup wizard, initialize the proposed
ERPNext foundations, then run:

```bash
bench scenario presentation-demo
```

The resulting Scenario Run exposes **Open Presentation**. Its read-only Desk
surface derives branded metrics, recent activity, and a guided ERPNext tour
from the run's recorded capabilities and real documents. Branding includes a
deterministic color system and optional inline SVG mark; supported locale pairs
receive curated bilingual headings. Presentation is refused unless validation
has zero errors and warnings and its persisted quality report is `Ready`.
Approved presentation exports contain the versioned specification, hashes,
identity, and copy—never provider credentials.

Inspect site readiness without changing any records or settings:

```bash
bench scenario preflight
bench scenario preflight --json
```

Inspect the installed capability contract:

```bash
bench scenario capabilities
bench scenario describe
```

Validate and plan the committed smoke scenario without generating records:

```bash
bench scenario validate-spec \
  apps/frappe_scenario/examples/hvac_kuwait_smoke.json

bench scenario plan \
  apps/frappe_scenario/examples/hvac_kuwait_smoke.json
```

Generate it after reviewing the plan:

```bash
bench scenario run \
  apps/frappe_scenario/examples/hvac_kuwait_smoke.json
```

The command prints the `Scenario Run` name. Use it for the remaining lifecycle:

```bash
bench scenario status SCN-RUN-YYYY-NNNNN
bench scenario validate SCN-RUN-YYYY-NNNNN
bench scenario export SCN-RUN-YYYY-NNNNN
bench scenario cleanup SCN-RUN-YYYY-NNNNN
```

Pass `--background` to `scenario run` to enqueue generation on the long queue.
The Bench worker must be running before using background mode.

Long runs commit after each provider phase. `status` reports completed/total
phases, the active phase, attempt counts, and the stable input/output
fingerprints for every checkpoint. Recovery commands are:

```bash
bench scenario cancel SCN-RUN-YYYY-NNNNN
bench scenario resume SCN-RUN-YYYY-NNNNN
bench scenario retry SCN-RUN-YYYY-NNNNN
bench scenario rollback-phase SCN-RUN-YYYY-NNNNN
```

Cancellation is cooperative and takes effect only between provider phases, so
an indivisible ERPNext transaction is never stopped halfway through. `resume`
continues a failed or cancelled run; `retry` is the explicit failed-phase form.
`rollback-phase` is deliberately limited to the latest committed phase of a
failed or cancelled run, then leaves it ready to resume. Full `cleanup` remains
available at every supported scale and consults only the ownership manifest.

### Realistic scale profiles

`medium` models 12–24 months and defaults to 24 months, with thousands of
linked business documents. `large` models 24–36 months and defaults to 36
months, with tens of thousands of documents; it always carries a prominent
large-run warning and requires the normal explicit run approval.

Counts are derived from business activity and lifecycle ratios. Seasonal
monthly demand drives sales and purchases; fulfillment ratios drive deliveries
and receipts; invoicing and payment behavior drive books and ageing. Customer
and supplier concentration is a bounded long-tail distribution. Catalog costs,
selling margins, item lead times, stock cover, and regional seasonality remain
deterministic under the scenario seed.

Both `scenario plan` and onboarding preview report estimated manifest
documents, underlying database rows, storage range, and controller runtime.
These are planning ranges—not quotas—because ERPNext controllers create child,
ledger, and stock rows according to the resolved business lifecycle.

### Operational breadth

Everyday and complex depth presets include commercial and accounting controls,
not just order volume. The generated lifecycle now covers opportunities and
submitted quotations, customer credit limits, price lists and discounts,
partial fulfillment, sales returns and credit notes, purchase returns and debit
notes, payment schedules and ageing, inter-warehouse transfers, bank statement
matching, and period closing.

Indirect tax is deliberately opt-in through
`accounting_controls.indirect_tax_rate`. When specified, scenario-owned sales
and purchase tax templates are applied to transactions. When omitted, Frappe
Scenario does not guess a country's tax law. Bank reconciliation is derived
from eligible generated Payment Entries, so a very short scenario may
legitimately have no statement matches even though the capability is enabled.

Assets, projects, manufacturing, HRMS, and regional compliance remain separate
future providers; they are not implied by the core trading lifecycle.

### Inspecting another development site

`bench start` serves the Bench default site. To inspect a different site without
changing that default, run a dedicated development server on an unused port:

```bash
bench --site <site-name> serve --port 8015
```

Then open `http://<site-name>:8015`. Ensure the site hostname resolves to
`127.0.0.1` (and optionally `::1`) in `/etc/hosts`. Use the Bench's persistent
development terminal/session for the server and avoid starting duplicate Bench
services.

## AI adapter and external-agent boundary

The provider-neutral adapter contract currently builds secret-free structured
requests but does not yet execute outbound model calls. OpenAI is the first
built-in adapter. Its optional API credential is stored only in the Password
field of `Scenario AI Provider`, using Frappe's encrypted password storage; it
is never returned by the adapter-discovery API.

The existing external-agent workflow remains fully supported. An agent such as
Claude or Codex can:

1. Call `frappe_scenario.api.capabilities.describe_capabilities`.
2. Call `frappe_scenario.api.agent.compile_brief` to obtain the schema,
   capability catalogue, constraints, and compilation instructions.
3. Compile the user's brief outside the app.
4. Submit the result with `frappe_scenario.api.agent.submit_draft`.
5. Leave the resulting `Scenario AI Draft` for human review and approval.

The submitted specification is treated as untrusted data. Only registered
provider paths and schema-valid values can reach the deterministic generator.

### Built-in AI Brief compilation

A System Manager may create and enable a `Scenario AI Provider` record for
`openai`, store the API key in its encrypted credential field, and optionally
select a model. The built-in workflow is then available through the POST-only
method `frappe_scenario.api.ai.compile_brief`. It:

1. Sends the brief, constraints, current schema, and current capability
   catalogue through the registered adapter.
2. Requires structured output and validates the returned specification using
   the same schema and semantic checks as a hand-authored specification.
3. Creates a `Scenario AI Draft` containing the original model output,
   editable specification, assumptions, inferred values, model/adapter/prompt
   versions, catalogue hash, response ID, usage, and hashes.
4. Leaves the draft in `Pending Review`; it never starts generation.

Approval is refused if the site's capability catalogue changed after
compilation. Credentials are added only at the HTTP execution boundary, are
sent only to the official OpenAI Responses endpoint, and are never stored in
the draft or returned by Scenario APIs.

### AI plausibility review

After saving the onboarding preview, a System Manager can POST to
`frappe_scenario.api.ai.review_onboarding_preview`. The review receives only a
qualitative projection: names, contacts, regional address text, product names
and descriptions, and transaction-story links. Prices, costs, quantities,
dates, document state, stock, taxes, and accounting are excluded from the
request and remain deterministic.

The result is stored as a pending `Scenario AI Review`. Proposed textual
replacements remain suggestions and cannot alter ERPNext records. A person may
approve or reject the review through the corresponding methods in
`frappe_scenario.api.ai`. Approved artifacts are cached by input, provider,
model, and prompt fingerprint, so an identical review is reused without
another model call.

### Grounded scenario tutor

`frappe_scenario.api.ai.ask_scenario_tutor` accepts a Scenario Run and a
learning question. Its bounded evidence bundle contains only manifest-owned
scenario documents, Scenario Events, and metadata for the projected ERPNext
fields. The structured response must classify every claim as an ERPNext fact,
scenario fact, or inference, and every claim must cite an evidence identifier
that was actually supplied. Invented citations are rejected.

Tutor responses are stored as immutable `Scenario Tutor Exchange` records with
clickable document citations and an evidence fingerprint. The tutor is always
read-only. It may describe a possible correction, but the response cannot
execute it. `confirm_tutor_corrections` records explicit human confirmation for
audit purposes and still executes no action.

## Developer and CI datasets

`scenario developer` is the noninteractive lifecycle surface. It always emits
one versioned JSON envelope and never prompts. `plan` and `generate` accept a
specification path; `validate`, `export`, and `cleanup` accept a Scenario Run
ID.

```bash
bench scenario developer plan examples/hvac_kuwait_smoke.json \
  --seed 20260801 --scale smoke --anchor-date 2026-08-01 \
  --partial-delivery-ratio 0.5 --return-ratio 0.25 \
  --provider erpnext.selling --provider erpnext.payments

bench scenario developer generate examples/hvac_kuwait_smoke.json \
  --seed 20260801 --output /tmp/scenario-generate.json
bench scenario developer validate SCN-RUN-2026-00001
bench scenario developer export SCN-RUN-2026-00001 \
  --output /tmp/scenario-export.json
bench scenario developer cleanup SCN-RUN-2026-00001
```

Advanced deterministic overrides use `/json/pointer=JSON`; values are decoded
as JSON and are never evaluated as code. Validation exclusions are explicit
and repeatable:

```bash
bench scenario developer plan examples/hvac_kuwait_smoke.json \
  --set '/catalog/item_count=75' \
  --set '/operations/warranty_claims=0.2' \
  --skip-rule erpnext.payments.overdue_profile
```

The stable process exit codes are `0` success, `10` invalid specification or
override, `20` site-safety refusal, `30` generation/execution failure, `40`
validation failure, and `50` blocked cleanup. Click reserves exit code `2` for
command-line usage errors. The same envelopes are available to System Managers
through `developer_specification` and `automate_developer` in
`frappe_scenario.api.runs`.

## Release audit

Before tagging a revision, run the read-only release audit on every supported
site and test the same signed Git commit in each Bench:

```bash
bench --site <site> scenario release-audit
bench --site <site> scenario release-audit --json
```

The audit checks source packaging boundaries, versioned schema metadata,
System Manager-only DocType permissions, encrypted credential metadata,
migration structure, installed applications, synchronized DocTypes,
compatibility adapters, documentation, and the disposable-site safety posture.
It never returns credentials or reads their values. A blocked audit exits with
status `60`.

The release matrix consists of the pure, `frappe_site`, and `erpnext_site`
tiers on v15, v16, and current develop, followed by `bench migrate`, an
uninstall/reinstall cycle on a clean disposable acceptance site, artifact
inspection, and this audit. Local `SCENARIO_PLAN.md` and `DECISIONS.md` files
must remain ignored and absent from wheels and source distributions.

## Tests

Pure tests need no site:

```bash
cd /path/to/frappe-bench
env/bin/python -m pytest -m pure \
  apps/frappe_scenario/frappe_scenario/tests -q
```

Site tiers require a disposable site:

```bash
FRAPPE_SCENARIO_TEST_SITE=scenario15.local \
  env/bin/python -m pytest -m frappe_site \
  apps/frappe_scenario/frappe_scenario/tests -q

FRAPPE_SCENARIO_TEST_SITE=scenario15.local \
  env/bin/python -m pytest -m erpnext_site \
  apps/frappe_scenario/frappe_scenario/tests -q
```

The ERPNext tier writes and then removes real documents. It proves planning,
manifest ownership, validation, balanced books, cleanup, and deterministic
regeneration.

Supported compatibility targets are Frappe/ERPNext v15, v16, and current
develop. Each compatibility Bench must test the exact same committed revision.

## Current boundaries

- HVAC Distribution, General Trading, Distribution and Wholesale, Retail, and
  Professional Services are lifecycle-validated at smoke scale. Medium and
  large profiles have deterministic volume and resource-planning coverage.
- OpenAI adapter discovery, encrypted configuration, structured request
  execution, reviewable AI Brief compilation, and human-approved qualitative
  plausibility review are implemented. The grounded tutor is implemented as a
  read-only, citation-validated learning workflow.
- Presentation Demo provides deterministic identity, optional logo, bilingual
  polish, recent evidence-backed activity, metrics, and a guided Desk tour. It
  is published only for warning-free, quality-ready runs.
- No Crispy Print or other third-party app code is modified or imported.
- HRMS, manufacturing, projects, assets, lending, and regional compliance
  remain future optional providers. Manufacturing and Construction/Project
  Contracting archetypes stay unpublished until those providers pass their
  declared acceptance contracts.

## License

GPL-3.0-or-later.
