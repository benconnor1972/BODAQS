# Applying skills to BODAQS engineering

Use the smallest workflow that addresses the task. Routine edits do not require
a design interview or a new specification. Existing user decisions and repository
instructions take precedence over upstream skill defaults.

## Design and specifications

Use `grill-with-docs` to clarify an unsettled design, with its supporting
`grilling` and `domain-modeling` skills. Resolve questions from repository facts
before asking the user. Use `to-spec` once the conversation contains the decisions;
follow the tracker preview rules before publishing.

For changes spanning disciplines, identify:

- The requirement and measurable acceptance criteria.
- Electrical, protocol, timing, data-format, and configuration interfaces affected.
- Board variant, wiring assumptions, component revisions, units, and timestamps.
- Startup, disconnection, invalid/stale data, overload, and recovery behavior.
- The evidence needed to distinguish a proposal from a verified result.

## Software

Use the existing test suites and configurations in the affected application or
analysis package. Apply `tdd` at agreed public interfaces when appropriate, using
independent expected results. Do not add tests that merely mirror implementation
or tests for low-impact, reversible documentation/configuration edits.

## Firmware

Consult `skills/firmware-build/SKILL.md`, `firmware/platformio.ini`, and the
existing firmware test harnesses. Select the board/environment explicitly.
Use existing host tests for logic and protocols, target compilation for hardware
integration, and on-device checks for timing and physical behavior.

Review sampling budgets, bus contention, blocking operations, allocations in fast
paths, buffering, startup order, logging integrity, and fault recovery when relevant.
A passing host test or compile is not evidence that physical timing works.
Record manual device checks still needed, including board and firmware versions.
Do not flash a device merely because a design or review skill is running.

## Hardware

Use clarification and specification skills for requirements, interface contracts,
component trade-offs, design reviews, and bring-up plans. Base electrical claims
on the exact component datasheet, calculations, or measured evidence, and label
unverified wiring/board assumptions.

Choose checks appropriate to the change: schematic/ERC and PCB/DRC review,
power/current and voltage margins, pull-ups and logic compatibility, timing,
connector pinouts, simulation, and bench measurements. Software tests do not
establish electrical correctness. Record instruments, test conditions, board
revision, expected limits, and observations for physical validation.

## Debugging and review

Use `diagnosing-bugs` to establish a reproducible failure before changing behavior.
For physical faults, use a repeatable bench procedure with observable pass/fail
criteria when an unattended software loop cannot reproduce the symptom. State
missing access or measurements explicitly rather than inventing results.

Use `code-review` for an explicit review request. Scope the review to the requested
files/change, preserve unrelated staged and unstaged work, and never commit or
close issues solely because a skill's default workflow suggests doing so.
