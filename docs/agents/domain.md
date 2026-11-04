# Domain documentation

BODAQS starts with one shared domain context across electronics, firmware,
analysis, and applications.

- Use root `GLOSSARY.md` for agreed domain terms only. Create it when the first
  term is resolved; do not fill it with inferred definitions or implementation.
- Record significant, costly-to-reverse trade-offs under `docs/adr/` as
  `NNNN-short-title.md`. Create records when a real decision warrants one.
- Use the formats bundled with `.agents/skills/domain-modeling/`.
- Read the glossary, when present, and relevant ADRs before design/specification
  work. Surface conflicts rather than silently replacing existing decisions.
- Existing contracts under `docs/firmware/`, `docs/analysis/`, and
  `docs/interchange/` remain authoritative references. Link to them instead of
  duplicating their specifications in the glossary or an ADR.
- Keep design/reference material in its existing area. Published documentation
  belongs in `bodocs/` only when a documentation-site update is requested.

Use consistent terms across a sensor's electrical interface, firmware data,
logged representation, and analysis interpretation. Board variants and firmware
versions are evidence about a design, not interchangeable names for it.
