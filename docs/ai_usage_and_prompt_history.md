Payment Reconciliation System — YottaFlex AI Candidate Assessment
This document organizes the key project-development prompts into a clear, professional record. The wording has been normalized for readability and represents the substantive requests reflected in the available development history; it is not a verbatim chat export.
1. Requirements and solution design
Prompt 1 — Interpret the assessment requirements
Review the payment reconciliation assessment brief and submission guidelines. Identify the required functionality, expected artifacts, constraints, validation expectations, and submission requirements. Translate these into a practical implementation plan and state any assumptions clearly.
Prompt 2 — Define the project architecture
Design a maintainable, locally runnable Python solution for payment reconciliation. Separate synthetic data generation, event processing, reconciliation, validation, exporting, API routes, tests, and documentation into clearly defined modules. Explain the responsibility of each component and how data moves through the workflow.
Prompt 3 — Review the existing implementation
Inspect the existing project against the assessment brief. Identify gaps in functionality, edge-case coverage, data consistency, reproducibility, testing, documentation, and ease of execution. Recommend targeted improvements while retaining useful existing work.
2. Synthetic data and event generation
Prompt 4 — Build a reproducible data generator
Implement a configurable synthetic data generator for merchants, payment orders, payment attempts, processor events, settlement batches and lines, and bank-statement records. Use deterministic generation where appropriate, ensure relationships are internally consistent, and support both small development datasets and larger validation datasets.
Prompt 5 — Enforce realistic data relationships
Validate that generated records follow logical lifecycle rules. Ensure timestamps and identifiers are consistent across related entities, avoid impossible sequences such as settlements occurring before the associated captures, and ensure payment attempts and processor events are linked correctly.
Prompt 6 — Add controlled ground-truth scenarios
Generate explicit, labelled scenarios for the required reconciliation edge cases. Keep the ground-truth labels separate from the data used by the reconciliation engine so that validation measures the engine's own decisions rather than reading expected answers.
Prompt 7 — Handle event duplication and idempotency
Define and implement idempotency behavior that distinguishes repeated delivery of the same webhook from separate legitimate events or attempts. Ensure the idempotency key includes the fields required to avoid incorrectly treating distinct declines or attempts as duplicates.
3. Payment and settlement processing
Prompt 8 — Implement the reconciliation engine
Implement the core reconciliation workflow that derives expected settlement amounts from payment and processor events and compares the results with bank-statement records. Keep the matching rules explicit, deterministic, and independent of ground-truth labels.
Prompt 9 — Calculate monetary values consistently
Represent monetary values using integer minor units wherever appropriate. Apply the documented rounding method consistently, including half-even rounding where specified. Document the calculation of fees, net payouts, settlement totals, and any rounding boundaries.
Prompt 10 — Match settlement batches and bank records
Implement matching using the configured amount tolerance and date window. Support settlement payouts that arrive as multiple bank-statement tranches, and define how tranche totals are compared with the expected net payout. Ensure each match decision and exception has an understandable reason.
Prompt 11 — Detect required exceptions
Detect and classify the required reconciliation edge cases, including missing bank records, amount mismatches, currency mismatches, date mismatches, duplicate bank records, and unmatched bank records. Preserve enough identifiers and context to make exceptions traceable and suitable for review.
Prompt 12 — Cover additional payment lifecycle cases
Review and test refunds, duplicate webhook deliveries, delayed settlements, declined attempts, missing payouts, and other lifecycle cases defined by the assessment. Ensure each scenario has consistent source data, a deterministic expected result, and an explicit validation check.
Prompt 13 — Support resolution and history
Represent exception resolutions using clear, valid resolution types and retain appropriate history. Validate that each resolution is permitted for the associated exception type and that repeated workflow execution does not silently duplicate exception history.
4. Validation and quality checks
Prompt 14 — Build a ground-truth validator
Create a validator that compares actual reconciliation outputs with the expected results for the labelled scenarios. Report missed exceptions, unexpected exceptions, and scenario-level pass or failure results. The validator must not feed ground-truth labels into the reconciliation engine.
Prompt 15 — Test the important edge cases
Create automated tests for the required anomaly types and important boundary conditions, including empty or small datasets, amount tolerances, date windows, duplicate events, refunds, delayed settlements, missing payouts, and repeated workflow runs. Use focused fixtures so each test checks a defined behavior.
Prompt 16 — Improve validation performance
Review the validator and full-size workflow for performance bottlenecks. Replace unnecessarily quadratic comparisons with more efficient lookups or indexing where appropriate, while preserving deterministic results and clear error reporting.
Prompt 17 — Verify reproducibility
Add a reproducibility check that confirms the generator and workflow produce consistent outputs when run with the same configuration and seed. Make sure output formats and required output folders are retained across runs, including JSON outputs when enabled.
Prompt 18 — Verify the end-to-end workflow
Run the documented workflow using both a small dataset and the full validation dataset where supported. Confirm that generation, processing, reconciliation, validation, and exporting complete successfully. Record actual test and validation results rather than assuming success from code inspection.
5. API, execution, and documentation
Prompt 19 — Provide a small Flask API
Expose the relevant workflow functionality through clear Flask routes, including suitable health and status endpoints. Validate request parameters, return useful error messages, and keep business logic in the service layer rather than embedding it in route handlers.
Prompt 20 — Make execution straightforward
Provide clear commands for installing dependencies, generating data, running the workflow, performing reproducibility checks, executing tests, and starting the API. Ensure that command-line arguments and examples match the implementation in the repository.
Prompt 21 — Document architecture and data fields
Write project documentation that explains the architecture, workflow stages, entity relationships, identifier patterns, field definitions, reconciliation rules, exception types, resolution behavior, validation approach, and known limitations. Include a walkthrough with examples that can be checked against the code and generated output.
Prompt 22 — Review the submission package
Compare the final repository with the assessment brief and submission requirements. Check that the core implementation is executable, relevant tests and validation instructions are included, generated data is handled intentionally, and the repository does not contain credentials, local environment files, or unrelated artifacts.
Prompt 23 — Diagnose and fix observed failures
Use the supplied command output, test failures, and relevant source code to identify reproducible issues. Apply focused changes, rerun the affected tests and workflow, and report which checks passed. Avoid claiming that an issue is fixed until the result has been verified.
6. Development review topics
The following technical topics are documented as part of the project's review and walkthrough:
- Integer minor units and consistent rounding for monetary amounts.
- Event lifecycle, idempotency, and the difference between webhook redelivery and distinct payment attempts.
- Calculation of net settlement payouts and aggregation of bank-statement tranches.
- Amount tolerance and date-window rules used for matching.
- Separation of ground-truth validation from the reconciliation decision process.
- Reproducibility, exception traceability, resolution history, and the limitations of the included test scenarios.
7. Tools and use
Claude and ChatGPT were used at different stages for requirements review, implementation guidance, code review, debugging, test development, workflow validation, and documentation. The project was iterated using test and workflow results to identify and address issues.


## Accuracy and transparency note

The prompts in this document have been professionally organized and edited for readability based on the available project-development history. They represent the key requests reflected in that history and are not a verbatim transcript of every AI conversation. AI responses are omitted. This document does not claim that the edited wording reproduces the original prompts word for word.