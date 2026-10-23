import copy
import json
import tempfile
import unittest
from pathlib import Path
from claims_pipeline import aggregate, compare, validate, vote, indexed, load_jsonl

def claim(effect='write', polarity='affirmed', scope='global', actor='tool',
          condition=None, mode=None, target=None, domain=None, evidence='Writes.'):
    return {'effect': effect, 'polarity': polarity, 'scope': scope, 'actor': actor,
            'condition': condition,
            'mode': mode or 'unknown' if effect == 'write' else None,
            'target': target or 'unspecified' if effect == 'network' else None,
            'interaction_domain': domain or 'unspecified' if effect == 'network' else None,
            'evidence': evidence}

def example(claims=(), description=None):
    if description is None:
        description = ' '.join(dict.fromkeys(c['evidence'] for c in claims)) or 'No operation described.'
    return ({'tool_id': 'test:1', 'description': description},
            {'schema_version': '2.0', 'tool_id': 'test:1', 'claims': list(claims),
             'needs_review': False, 'notes': []})

class Rules(unittest.TestCase):
    def test_empty_claims_are_not_stated(self):
        s, p = example()
        self.assertTrue(all(x['status'] == 'not_stated' for x in aggregate(s,p)['effects'].values()))

    def test_missing_description_needs_review(self):
        s, p = example(description='')
        self.assertTrue(aggregate(s,p)['needs_review'])

    def test_scoped_denial_does_not_become_global(self):
        s,p = example([claim(polarity='denied',scope='filesystem',evidence='No filesystem access.')])
        x = aggregate(s,p)['effects']['write']
        self.assertEqual(x['status'],'not_stated')
        self.assertTrue(x['scoped_denial'])

    def test_conditional_denial_does_not_become_global(self):
        s,p = example([claim(polarity='denied',condition='dry_run=true',evidence='No writes in dry run.')])
        x = aggregate(s,p)['effects']['write']
        self.assertEqual(x['status'],'not_stated')
        self.assertTrue(x['conditional_denial'])

    def test_broad_denial(self):
        s,p = example([claim(polarity='denied',evidence='No state changes.'),
                       claim('delete','denied',evidence='No state changes.')])
        x = aggregate(s,p)
        self.assertEqual(x['effects']['write']['status'],'denied')
        self.assertEqual(x['effects']['delete']['status'],'denied')

    def test_provider_expiry_is_excluded(self):
        s,p = example([claim('delete',actor='provider',evidence='Provider deletes expired sessions.')])
        self.assertEqual(aggregate(s,p)['effects']['delete']['status'],'not_stated')
        self.assertFalse(compare(s,p,{'destructiveHint':False})['candidate_inconsistencies'])

    def test_other_tool_action_excluded(self):
        s,p = example([claim(actor='other_tool',evidence='Then call submit_work to send it.')])
        self.assertEqual(aggregate(s,p)['effects']['write']['status'],'not_stated')

    def test_unknown_actor_is_review(self):
        s,p = example([claim(actor='unknown')])
        r = compare(s,p,{'readOnlyHint':True})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['needs_review'])

    def test_same_scope_conflict_blocks_candidate(self):
        s,p = example([claim(),claim(polarity='denied',evidence='Never writes.')])
        r = compare(s,p,{'readOnlyHint':True})
        self.assertEqual(r['effects']['write']['status'],'uncertain')
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['review_findings'])

    def test_unknown_condition_overlap_requires_review(self):
        s,p = example([claim(condition='fresh=true'),
                       claim(polarity='denied',condition='fresh=false',evidence='No writes if fresh=false.')])
        r=compare(s,p,{'readOnlyHint':True})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['effects']['write']['possible_internal_conflicts'])

    def test_disjoint_scopes_do_not_conflict(self):
        s,p=example([claim(scope='database'),
                     claim(polarity='denied',scope='filesystem',evidence='No filesystem access.')])
        self.assertEqual(aggregate(s,p)['effects']['write']['status'],'affirmed')
        self.assertTrue(compare(s,p,{'readOnlyHint':True})['candidate_inconsistencies'])

    def test_unknown_scope_overlap_blocks_candidate(self):
        s,p=example([claim(scope='database'),
                     claim(polarity='denied',scope='records',evidence='Does not change records.')])
        self.assertFalse(compare(s,p,{'readOnlyHint':True})['candidate_inconsistencies'])
        self.assertTrue(aggregate(s,p)['needs_review'])

    def test_omitted_hints_not_explicit(self):
        s,p=example([claim()])
        r=compare(s,p,{})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertEqual(r['annotation_states']['readOnlyHint'],'omitted')

    def test_execute_alone_is_review(self):
        s,p=example([claim('execute',evidence='Runs Python code.')])
        r=compare(s,p,{'readOnlyHint':True})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['review_findings'])

    def test_destructive_inapplicable_for_readonly(self):
        s,p=example([claim('delete',evidence='Deletes a record.')])
        r=compare(s,p,{'readOnlyHint':True,'destructiveHint':False})
        self.assertEqual([x['hint'] for x in r['candidate_inconsistencies']],['readOnlyHint'])

    def test_additive_versus_modifying_write(self):
        for mode, expected in [('additive',False),('modifying',True),('mixed',True),('unknown',False)]:
            with self.subTest(mode=mode):
                s,p=example([claim(mode=mode)])
                r=compare(s,p,{'destructiveHint':False})
                self.assertEqual(bool(r['candidate_inconsistencies']),expected)
                if mode=='unknown': self.assertTrue(r['review_findings'])

    def test_fixed_service_can_have_open_domain(self):
        s,p=example([claim('network',target='named_service',domain='open',
                          evidence='Uses a fixed API to search the public web.')])
        self.assertTrue(compare(s,p,{'openWorldHint':False})['candidate_inconsistencies'])

    def test_caller_url_can_have_closed_domain(self):
        s,p=example([claim('network',target='caller_supplied',domain='closed',
                          evidence='Fetches only caller URLs from the fixed allowlist.')])
        self.assertFalse(compare(s,p,{'openWorldHint':False})['candidate_inconsistencies'])

    def test_unknown_domain_is_review(self):
        s,p=example([claim('network',target='named_service',evidence='Contacts ServiceX.')])
        r=compare(s,p,{'openWorldHint':False})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['review_findings'])

    def test_uncertain_effect_is_not_automatic_candidate(self):
        s,p=example([claim(polarity='uncertain')])
        r=compare(s,p,{'readOnlyHint':True})
        self.assertFalse(r['candidate_inconsistencies'])
        self.assertTrue(r['review_findings'])

    def test_exact_evidence_enforced(self):
        s,p=example([claim()]);p['claims'][0]['evidence']='Invented quote'
        with self.assertRaises(ValueError):validate(s,p)

    def test_inapplicable_fields_rejected(self):
        s,p=example([claim('read',evidence='Reads.')])
        p['claims'][0]['mode']='additive'
        with self.assertRaises(ValueError):validate(s,p)

    def test_extra_and_duplicate_claims_rejected(self):
        s,p=example([claim()]);p['claims'].append(copy.deepcopy(p['claims'][0]))
        with self.assertRaises(ValueError):validate(s,p)
        s,p=example();p['extra']='x'
        with self.assertRaises(ValueError):validate(s,p)

    def test_duplicate_tool_ids_rejected(self):
        with self.assertRaises(ValueError):indexed([{'tool_id':'x'},{'tool_id':'x'}],'test')

    def test_not_stated_vote_is_retained(self):
        s,p=example();a=aggregate(s,p)
        self.assertEqual(vote(a,a)['effects']['write']['status'],'not_stated')

    def test_agreed_denial_is_retained(self):
        s,p=example([claim(polarity='denied',evidence='Never writes.')]);a=aggregate(s,p)
        self.assertEqual(vote(a,a)['effects']['write']['status'],'denied')

    def test_vote_disagreement_and_review_preserved(self):
        s,p=example([claim()]);a=aggregate(s,p)
        s,q=example();b=aggregate(s,q)
        self.assertEqual(vote(a,b)['effects']['write']['status'],'uncertain')
        a['needs_review']=True
        self.assertTrue(vote(a,a)['needs_review'])

    def test_invalid_jsonl_not_silently_repaired(self):
        with tempfile.TemporaryDirectory() as d:
            f=Path(d)/'bad.jsonl';f.write_text('{"x":1}'+chr(92)+'\n',encoding='utf-8')
            with self.assertRaises(ValueError):load_jsonl(f)

    def test_uncertain_not_hidden_by_global_denial(self):
        s,p=example([claim(polarity='denied',evidence='Never writes.'),
                     claim(polarity='uncertain',evidence='May sync records.')])
        self.assertEqual(aggregate(s,p)['effects']['write']['status'],'uncertain')

if __name__=='__main__':
    unittest.main()
