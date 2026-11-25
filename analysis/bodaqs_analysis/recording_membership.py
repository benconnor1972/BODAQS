"""Expose requested, excluded and uncertain zero-data sources without inventing samples."""
from collections.abc import Mapping
import copy


def recording_membership(metadata, summary):
    header = metadata.get('recording_membership')
    if not isinstance(header, Mapping):
        return {}, []  # Historical files do not have this declaration.
    result = {'preparation': copy.deepcopy(dict(header)), 'finalization': None, 'sources': []}
    warnings = []

    def masks(value):
        if not isinstance(value, Mapping) or value.get('schema') != 'bodaqs.recording_membership.v1':
            return None
        fields = [value.get(name) for name in ('requested_mask', 'selected_mask', 'excluded_mask')]
        if any(type(field) is not int or not 0 <= field <= 0xffffffff for field in fields):
            return None
        requested, selected, excluded = fields
        if selected & excluded or selected | excluded != requested:
            return None
        return requested, selected, excluded

    initial = masks(header)
    footer = summary.get('recording_membership') if isinstance(summary, Mapping) else None
    final = masks(footer)
    if initial is None:
        return result, ['recording_membership_invalid:preparation_masks']
    if footer is not None:
        result['finalization'] = copy.deepcopy(footer)
        if final is None or final[0] != initial[0] or final[1] & ~initial[1]:
            final = None
            warnings.append('recording_membership_invalid:finalization_masks')
    sources = header.get('sources')
    if not isinstance(sources, list):
        return result, warnings + ['recording_membership_invalid:source_inventory']
    seen_indices, seen_ids = set(), set()
    for source in sources:
        if not isinstance(source, Mapping):
            warnings.append('recording_membership_invalid:source_identity')
            continue
        index, identity = source.get('configured_index'), source.get('sensor_id')
        if (type(index) is not int or not 0 <= index < 32 or not isinstance(identity, str) or not identity
                or index in seen_indices or identity in seen_ids):
            warnings.append('recording_membership_invalid:source_identity')
            continue
        seen_indices.add(index)
        seen_ids.add(identity)
        bit = 1 << index
        excluded = bool((final or initial)[2] & bit)
        entry = {'configured_index': index, 'sensor_id': identity, 'sensor_type': source.get('sensor_type'),
                 'requested': bool(initial[0] & bit), 'selected_at_preparation': bool(initial[1] & bit),
                 'selected_at_finalization': bool(final[1] & bit) if final else None,
                 'exclusion_declared': excluded, 'sample_count_inferred': False}
        if excluded:
            entry['exclusion_reason'] = (source.get('exclusion_reason')
                                         if initial[2] & bit else 'not_admitted_at_finalization')
            warnings.append(f'recording_source_excluded:{identity}:{entry["exclusion_reason"]}')
        elif final is None and entry['requested']:
            entry['membership_outcome'] = 'unknown_without_valid_final_membership'
        result['sources'].append(entry)
    return result, warnings
