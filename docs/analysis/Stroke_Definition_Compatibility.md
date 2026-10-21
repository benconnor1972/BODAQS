# Stroke definition compatibility

The desktop default event schema is `event_schema_combined.yaml` in the Import
Manager asset package. Provisioning copies it into the shared event-schemas
folder as `event_schema.yaml` for new configurations. Existing schemas and
preprocessing profiles are preserved unless explicitly replaced by the user.

The combined schema keeps BODAQS `compressions_all` and `rebounds_all`, and adds
BYB-style `compression_byb` and `rebound_byb`. It also retains `bottom_out` and
`Jump`. All event metrics use zero additional smoothing and zero onset exclusion;
the motion derivation filters remain controlled by the preprocessing profile.
The BODAQS displacement acceptance condition remains greater than 5 mm.

The BYB-style events pair adjacent displacement minima/maxima within a continuous
signal segment, reject excursions of 1 mm or less after pairing, and impose a
5 second pairing limit matching their extraction windows. They use BODAQS wheel
signals and do not reproduce the reference's shock-domain pairing, boundary
quirks, filters, or sample-based velocity summaries.

In Simple Suspension Analysis, Display options > Compatibility contains
**Use BYB stroke definition**, initially checked. Clearing it selects the BODAQS
events. The choice is saved with the analysis display settings. Velocity and
stroke-length distributions, their statistics, compression/rebound balance
plots, and stroke event counts all use the selected definition. Displacement
distributions continue to use continuous signal samples. Jumps and bottom-outs
retain their own definitions and counts; the phase diagram remains signal-based.

The browser fetches both metric families once and selects the requested family
before applying time windows, activity masks, scenarios, or track sectors. Its
cache version changes to avoid reusing older entries containing only BODAQS
metrics. It never substitutes the other stroke definition when metrics are
missing. A message identifies missing session/end combinations and explains how
to reprocess or select the other definition. Adequacy accepts a complete pair
from either family, without combining compression from one with rebound from
the other.

Existing sessions require reprocessing with the combined schema to store both
families and use the new metric policy. Previously generated schema variants
and their historical metrics are unchanged.
