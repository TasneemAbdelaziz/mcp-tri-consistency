"""Claim-level extraction utilities v2. No LLM or network calls."""
import argparse
import json
from pathlib import Path

EFFECTS = ('read', 'write', 'delete', 'execute', 'network')
ROOT_KEYS = {'schema_version', 'tool_id', 'claims', 'needs_review', 'notes'}
CLAIM_KEYS = {'effect', 'polarity', 'scope', 'actor', 'condition', 'mode',
              'target', 'interaction_domain', 'evidence'}
STATES = {'affirmed', 'denied', 'uncertain', 'not_stated'}

def validate(source, result):
    if not isinstance(result, dict) or set(result) != ROOT_KEYS:
        raise ValueError('Invalid root keys')
    if result['schema_version'] != '2.0' or result['tool_id'] != source['tool_id']:
        raise ValueError('Schema version or tool ID mismatch')
    if type(result['needs_review']) is not bool:
        raise ValueError('needs_review must be boolean')
    if not isinstance(result['notes'], list) or any(type(x) is not str for x in result['notes']):
        raise ValueError('notes must be an array of strings')
    if not isinstance(result['claims'], list):
        raise ValueError('claims must be an array')
    seen = set()
    for c in result['claims']:
        if not isinstance(c, dict) or set(c) != CLAIM_KEYS:
            raise ValueError('Invalid claim keys')
        for key, options in {
            'effect': EFFECTS, 'polarity': ('affirmed', 'denied', 'uncertain'),
            'actor': ('tool', 'provider', 'other_tool', 'user', 'unknown')
        }.items():
            if c[key] not in options:
                raise ValueError('Invalid ' + key)
        if not isinstance(c['scope'], str) or not c['scope'].strip():
            raise ValueError('scope must be nonempty')
        if c['condition'] is not None and (not isinstance(c['condition'], str) or not c['condition'].strip()):
            raise ValueError('condition must be null or nonempty text')
        q = c['evidence']
        if not isinstance(q, str) or not q.strip() or q not in (source.get('description') or ''):
            raise ValueError('Evidence must be a nonempty exact description substring')
        if c['effect'] == 'write':
            if c['mode'] not in ('additive', 'modifying', 'mixed', 'unknown'):
                raise ValueError('write requires mode')
        elif c['mode'] is not None:
            raise ValueError('mode applies only to write')
        if c['effect'] == 'network':
            if c['target'] not in ('caller_supplied', 'named_service', 'unspecified'):
                raise ValueError('network requires target')
            if c['interaction_domain'] not in ('open', 'closed', 'unspecified'):
                raise ValueError('network requires interaction_domain')
        elif c['target'] is not None or c['interaction_domain'] is not None:
            raise ValueError('Network fields apply only to network')
        key = json.dumps(c, sort_keys=True)
        if key in seen:
            raise ValueError('Duplicate claim')
        seen.add(key)
    return result

def scope_overlap(a, b):
    """True, False or None. Do not infer arbitrary scope hierarchies."""
    if a == b or 'global' in (a, b):
        return True
    if {a, b} <= {'filesystem', 'database', 'memory', 'network'}:
        return False
    if {a, b} <= {'javascript', 'python'}:
        return False
    return None

def condition_overlap(a, b):
    if a is None or b is None or a == b:
        return True
    # Different strings are not proof of mutually exclusive conditions.
    return None

def relation(a, b):
    s, c = scope_overlap(a['scope'], b['scope']), condition_overlap(a['condition'], b['condition'])
    if s is False or c is False:
        return False
    return True if s is True and c is True else None

def aggregate(source, result):
    validate(source, result)
    summaries = {}
    review = result['needs_review'] or not bool(source.get('description'))
    for e in EFFECTS:
        indexed = [(i, c) for i, c in enumerate(result['claims']) if c['effect'] == e]
        own = [(i, c) for i, c in indexed if c['actor'] == 'tool']
        pos = [(i, c) for i, c in own if c['polarity'] == 'affirmed']
        neg = [(i, c) for i, c in own if c['polarity'] == 'denied']
        unc = any(c['polarity'] == 'uncertain' for _, c in own)
        definite, possible = [], []
        for pi, p in pos:
            for ni, n in neg:
                overlap = relation(p, n)
                if overlap is True:
                    definite.append([pi, ni])
                elif overlap is None:
                    possible.append([pi, ni])
        if definite:
            status = 'uncertain'
        elif pos:
            status = 'affirmed'
        elif unc:
            status = 'uncertain'
        elif any(c['scope'] == 'global' and c['condition'] is None for _, c in neg):
            status = 'denied'
        else:
            status = 'not_stated'
        unknown_actor = any(c['actor'] == 'unknown' for _, c in indexed)
        unresolved_network = e == 'network' and any(
            c['polarity'] != 'denied' and c['interaction_domain'] == 'unspecified' for _, c in own)
        needs = bool(definite or possible or unc or unknown_actor or unresolved_network)
        summaries[e] = {
            'status': status, 'needs_review': needs,
            'scoped_denial': any(c['scope'] != 'global' for _, c in neg),
            'conditional_denial': any(c['condition'] is not None for _, c in neg),
            'internal_conflicts': definite, 'possible_internal_conflicts': possible,
            'unknown_actor': unknown_actor
        }
        review = review or needs
    return {'tool_id': result['tool_id'], 'effects': summaries, 'needs_review': review,
            'claims': result['claims'], 'notes': result['notes']}

def hint_states(annotations):
    out = {}
    for key in ('readOnlyHint', 'destructiveHint', 'openWorldHint', 'idempotentHint'):
        value = annotations.get(key, 'omitted')
        if type(value) is bool:
            value = str(value).lower()
        if value not in ('true', 'false', 'omitted'):
            raise ValueError('Invalid annotation state: ' + key)
        out[key] = value
    return out

def compare(source, result, annotations):
    summary = aggregate(source, result)
    states = hint_states(annotations)
    candidates, reviews = [], []
    effective_readonly = states['readOnlyHint'] == 'true'  # omitted -> false
    for i, c in enumerate(result['claims']):
        if c['actor'] not in ('tool', 'unknown') or c['polarity'] == 'denied':
            continue
        e = c['effect']
        blocked = bool(summary['effects'][e]['internal_conflicts'] or
                       summary['effects'][e]['possible_internal_conflicts'] or
                       c['actor'] == 'unknown' or c['polarity'] == 'uncertain')
        def record(hint, reason, automatic):
            item = {'hint': hint, 'effect': e, 'claim_index': i, 'evidence': c['evidence'],
                    'scope': c['scope'], 'condition': c['condition'], 'reason': reason}
            (candidates if automatic and not blocked else reviews).append(item)
        if states['readOnlyHint'] == 'true':
            if e in ('write', 'delete'):
                record('readOnlyHint', 'Described state mutation', True)
            elif e == 'execute':
                record('readOnlyHint', 'Execution alone does not establish mutation', False)
        if states['destructiveHint'] == 'false' and not effective_readonly:
            if e == 'delete':
                record('destructiveHint', 'Described removal under additive-only policy', True)
            elif e == 'write' and c['mode'] != 'additive':
                record('destructiveHint', 'Modifying/mixed write or unresolved write mode',
                       c['mode'] in ('modifying', 'mixed'))
        if states['openWorldHint'] == 'false' and e == 'network':
            domain = c['interaction_domain']
            if domain != 'closed':
                record('openWorldHint', 'Open domain' if domain == 'open' else 'Unspecified domain',
                       domain == 'open')
    review = summary['needs_review'] or bool(reviews)
    return {'schema_version': '2.0', 'rule_profile': 'declaration_v2_2025-06-18',
            **summary, 'annotation_states': states,
            'candidate_inconsistencies': candidates, 'review_findings': reviews,
            'needs_review': review,
            'result': 'candidate_inconsistency' if candidates else 'review' if review
            else 'no_supported_inconsistency'}

def vote(a, b):
    """Diagnostic status vote; not a replacement for comparing full claims."""
    if a['tool_id'] != b['tool_id']:
        raise ValueError('Voting IDs differ')
    effects = {}
    for e in EFFECTS:
        x, y = a['effects'][e], b['effects'][e]
        if x['status'] not in STATES or y['status'] not in STATES:
            raise ValueError('Invalid vote state')
        same = x['status'] == y['status']
        status = x['status'] if same else 'uncertain'
        effects[e] = {'status': status, 'agreement': same,
                      'needs_review': bool(x['needs_review'] or y['needs_review'] or
                                           not same or status == 'uncertain')}
    return {'tool_id': a['tool_id'], 'effects': effects,
            'needs_review': a['needs_review'] or b['needs_review'] or
            any(v['needs_review'] for v in effects.values()),
            'usage': 'Diagnostic only; compare full claims separately'}

def load_jsonl(path):
    items = []
    for n, line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        if not line.strip():
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f'{path}: invalid JSON at line {n}; no silent repair') from exc
    return items

def indexed(items, label):
    out = {}
    for row in items:
        key = row['tool_id']
        if key in out:
            raise ValueError('Duplicate tool ID in ' + label)
        out[key] = row
    return out

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs', required=True)
    p.add_argument('--predictions', required=True)
    p.add_argument('--annotations')
    p.add_argument('--out', required=True)
    a = p.parse_args()
    inputs = indexed(load_jsonl(a.inputs), 'inputs')
    predictions = indexed(load_jsonl(a.predictions), 'predictions')
    if inputs.keys() != predictions.keys():
        raise ValueError('Predictions must match all and only input IDs')
    annotations = indexed(load_jsonl(a.annotations), 'annotations') if a.annotations else {}
    if a.annotations and not inputs.keys() <= annotations.keys():
        raise ValueError('Missing annotation IDs')
    results = [compare(s, predictions[k], annotations[k]['annotations']) if a.annotations
               else aggregate(s, predictions[k]) for k, s in inputs.items()]
    output = {'schema_version': '2.0', 'tools': len(results),
              'note': 'Development outputs, not independently validated accuracy', 'results': results}
    Path(a.out).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'tools': len(results), 'review_tools': sum(x['needs_review'] for x in results),
                      'candidate_tools': sum(bool(x.get('candidate_inconsistencies')) for x in results)}))

if __name__ == '__main__':
    main()
