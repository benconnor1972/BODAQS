# BODAQS Zero-Install Web Application Roadmap

**Status:** Discussion draft
**Date:** 2026-04-22
**Audience:** BODAQS project team

## Purpose

This document summarizes:

- the stated requirements for moving BODAQS analysis toward an internet-facing product
- the recommended architectural direction
- a phased implementation roadmap for a zero-install web application

## Current BODAQS Starting Point

BODAQS analysis is already part-way toward an application architecture.

Today, the system includes:

- reusable Python analysis code in `analysis/bodaqs_analysis/`
- notebook-based orchestration and UI in `analysis/*.ipynb`
- an explicit on-disk artifact model for processed sessions and derived outputs
- documented public analysis interfaces and contracts

This means the migration is not primarily about rewriting the analysis logic. It is mainly about replacing notebook-centric user interaction with a browser-based product while preserving the existing processing engine and artifact structure.

Relevant existing references:

- [`BODAQS_Public_API_Contract_v0.md`](./BODAQS_Public_API_Contract_v0.md)
- [`BODAQS_analysis_artifacts_specification_v0_2.md`](./BODAQS_analysis_artifacts_specification_v0_2.md)
- [`Overview/BODAQS_Analysis_Notebook_Overview.md`](./Overview/BODAQS_Analysis_Notebook_Overview.md)

## Stated Requirements

The requirements expressed so far are:

- BODAQS should evolve toward an internet-facing application rather than remaining a notebook-driven workflow.
- The application should present a more polished, product-like user experience than Jupyter notebooks.
- The underlying processing should generally reuse the same logic that currently exists in the analysis notebooks and extracted Python modules.
- Processing and visualization may be provided by the server.
- User data is allowed to pass through the server during use.
- The BODAQS operator should not be responsible for long-term safekeeping of end-user data.
- After a session is complete, raw files and preferably processed artifacts should live with the end user on their own resources.
- The preferred delivery model is zero-install, meaning a browser-based experience rather than a required desktop install.
- The target audience is ultimately outside users, not only the internal team.

## Key Implications

These requirements imply several important constraints.

First, this should be treated as a real product architecture, not simply "Jupyter on the internet." Notebook technology remains useful for development and internal exploration, but it should not be the primary end-user product surface.

Second, the system should minimize long-term server-side custody of customer files. The server can act as a temporary processing environment, but the saved canonical copy of user work should end up under the user's control.

Third, because the preferred model is zero-install, the browser experience must work well with ordinary upload and download flows. More advanced local-file features can be added where browser support allows, but they should be enhancements rather than core requirements.

## Recommended Architecture

The recommended direction is:

- build a browser-based application for end users
- keep the core BODAQS analysis engine in Python
- run analysis jobs on the server
- treat server storage as temporary scratch space rather than a permanent data vault
- make import and export of user-owned BODAQS workspaces a first-class feature

In practical terms, this means the browser is the polished interface, the server performs analysis, and the user saves the finished workspace bundle locally after processing.

### Recommended product model

1. A user uploads one or more log files and associated inputs.
2. The server performs preprocessing, event detection, metric extraction, and visualization preparation.
3. The user inspects results in the browser.
4. The user downloads a BODAQS workspace bundle containing the relevant raw inputs, processed artifacts, manifests, notes, and configuration.
5. The server deletes temporary working files after the session ends or after a short retention window.
6. A user who wants to continue later re-imports the previously exported bundle.

This model allows server-side compute without making the BODAQS operator the long-term custodian of customer datasets.

## Recommended Technical Stack

The following stack is recommended as the default path:

- **Backend API:** Python with FastAPI
- **Background processing:** worker-based job execution for long-running analysis tasks
- **Analysis engine:** the existing `analysis/bodaqs_analysis/` package
- **Frontend:** React or Next.js
- **Temporary storage:** server-side scratch storage with strict cleanup policy
- **Long-term user data:** downloaded workspace bundles controlled by the end user
- **Browser local storage:** only for convenience items such as UI state, not as the canonical saved copy of analysis data

This approach supports a polished product experience while preserving the current investment in the BODAQS analysis code and artifacts model.

## Proposed High-Level Architecture

```text
Browser UI
  -> Web frontend
  -> Backend API
  -> Background analysis workers
  -> existing bodaqs_analysis package
  -> temporary server-side scratch storage
  -> downloadable user-owned BODAQS workspace bundle
```

### Data ownership model

- The server may receive raw files temporarily in order to process them.
- The server may generate derived artifacts temporarily in order to display results.
- The server should not be treated as the authoritative long-term home of customer data.
- The canonical saved deliverable should be an exportable BODAQS workspace bundle that the user keeps.

## Why This Is Preferable To A Notebook-Derived Product

This approach is recommended over directly exposing notebook technology for end users because it provides:

- clearer separation between UI, backend logic, and persistence
- a better path to authentication, billing, observability, and product hardening
- better control over upload, retention, deletion, and privacy behavior
- a more predictable user experience for outside customers
- a lower risk of the product being tightly coupled to notebook session state

## Implementation Plan

### Phase 0: Define service boundaries

Goal: prepare the current analysis code for use behind an API.

Work in this phase:

- identify the stable backend entry points that the web product will call
- formalize which parts of the current notebook workflow are UI/orchestration versus reusable analysis logic
- confirm that the existing artifact model is suitable as the basis for an import/export workspace format
- identify any notebook-only dependencies that should not leak into the product backend

Expected outcome:

- a clear boundary between the analysis engine and the notebook UI layer

### Phase 1: Stabilize the backend analysis service

Goal: make the current Python processing logic callable as web jobs.

Work in this phase:

- wrap the current processing flow behind backend job endpoints
- preserve use of the current analysis package and artifact writers where possible
- add structured logging, error reporting, and progress reporting suitable for a web product
- validate that typical sessions can run without notebook state or manual notebook interaction

Expected outcome:

- a backend service that can ingest files, run BODAQS processing, and return structured job results

### Phase 2: Define the portable workspace bundle

Goal: make user-owned export and re-import a core product feature.

Work in this phase:

- define the canonical contents of a BODAQS workspace bundle
- include processed artifacts, manifests, notes, and relevant configuration
- decide whether raw uploaded source files are always included, optionally included, or policy-driven
- support import of a previously exported bundle so a user can reopen work later

Expected outcome:

- a versioned portable bundle format that becomes the main persistence boundary for end users

### Phase 3: Build the zero-install browser product

Goal: deliver the first browser-based user experience.

Work in this phase:

- create upload, configuration, processing-status, results, and export pages
- rebuild the highest-value notebook workflows as proper product pages
- keep browser-local storage limited to convenience state such as recent settings or draft forms
- support standard upload/download flows across mainstream browsers

Expected outcome:

- an internal alpha product that supports the main happy path without requiring installation

### Phase 4: External beta hardening

Goal: make the product safe and supportable for outside users.

Work in this phase:

- add authentication and account management
- add rate limiting, quotas, and job isolation
- enforce strict file validation and cleanup policies
- define and implement the temporary retention window for uploaded data and generated artifacts
- add monitoring, error capture, and operational dashboards
- document user-facing privacy and retention behavior clearly

Expected outcome:

- an externally usable beta with controlled operational risk

### Phase 5: Product maturity

Goal: improve usability and reduce friction without changing the zero-install principle.

Work in this phase:

- add progressive browser enhancements for better local save/open behavior where supported
- improve collaboration features only if they can be done without forcing long-term data custody
- improve onboarding, performance, resumability, and support tooling
- evaluate whether a later optional desktop wrapper is worthwhile, without changing the browser-first product model

Expected outcome:

- a more polished customer product built on the same core architecture

## Suggested First Deliverable

The first meaningful product milestone should support this single end-to-end flow:

1. Upload log files and related inputs.
2. Choose analysis settings or a preprocessing profile.
3. Run processing on the server.
4. Inspect key dashboards and results in the browser.
5. Export a BODAQS workspace bundle for local safekeeping.
6. Re-import that bundle later to continue work.

If this flow is solid, the product has a strong foundation. If this flow is weak, additional features will not fix the fundamental user experience.

## Design Principles For The Product

- Preserve the existing core analysis logic unless there is a strong reason to change it.
- Treat notebooks as development tools and internal reference implementations, not as the shipped product.
- Keep user data retention minimal and explicit.
- Make import/export and local ownership of saved work central to the workflow.
- Avoid storing large volumes of customer data long-term on BODAQS-controlled infrastructure.
- Prefer small, explicit contracts between frontend, backend, and artifacts over hidden state.

## Risks And Decisions To Resolve

The following decisions will materially affect implementation detail:

- how long temporary uploaded files and derived artifacts may remain on the server
- whether exported bundles always include raw inputs or only derived artifacts by default
- what browser support target is required for v1
- what authentication model is needed for outside users
- whether the first public release includes paid usage, quotas, or both
- how much of the current notebook feature set must be present in the first browser release

## Things To Avoid

- Exposing Jupyter or notebook sessions directly as the external product.
- Making browser storage the only saved copy of important user work.
- Rewriting the analysis engine prematurely when the current package can already serve as the backend.
- Moving all analysis state into a traditional database without a clear need.
- Quietly retaining customer datasets longer than the documented policy allows.

## Summary Recommendation

The recommended path is to build a zero-install browser application that uses the current BODAQS Python analysis engine on the server, keeps server-side file retention temporary, and makes user-owned workspace export/import a core part of the product model.

This is the best fit for the stated goals because it combines:

- a product-like experience for outside users
- reuse of the existing BODAQS analysis logic
- server-side processing and visualization
- reduced responsibility for long-term custody of customer data
- a clear migration path from the current notebook workflow
