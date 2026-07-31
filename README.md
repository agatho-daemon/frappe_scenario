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

## Quick start

Scenario commands use the Bench default site configured by `bench use`.
Supply `--site <site-name>` before `scenario` to target another site explicitly.

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

- Only the smoke-scale HVAC distribution vertical slice is proven end to end.
- OpenAI adapter discovery, encrypted configuration, structured request
  execution, reviewable AI Brief compilation, and human-approved qualitative
  plausibility review are implemented. The grounded tutor is implemented as a
  read-only, citation-validated learning workflow.
- No Crispy Print or other third-party app code is modified or imported.
- HRMS, manufacturing, projects, assets, lending, regional compliance, and
  broader archetypes remain future providers.

## License

GPL-3.0-or-later.
