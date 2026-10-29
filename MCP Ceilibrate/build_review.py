import csv, json, hashlib, shutil, zipfile, html
from pathlib import Path
from collections import OrderedDict, Counter
SRC=Path(r'D:\MCP Paper work\Week 1\Calibration30_Package\Menna_Calibration30_all_tools_labeled.csv')
OUT=Path('outputs/Calibration30_Review')
raw=SRC.read_bytes()
rows=list(csv.DictReader(SRC.open(encoding='utf-8-sig',newline='')))
fields=list(rows[0]); original=[r.copy() for r in rows]; changes=[]

def change(n, reason, **updates):
 r=rows[n-2]; before=r.copy(); r.update(updates)
 diff={k:{'before':before[k],'after':r[k]} for k in fields if before[k]!=r[k]}
 if diff: changes.append({'original_csv_record':n,'tool_id':r['tool_id'],'effect':r['effect'],'reason':reason,'changes':diff})

def unstated(n,reason):
 updates={k:'' for k in fields if k not in ('tool_id','description','effect')};updates['polarity']='not_stated'
 change(n,reason,**updates)

unstated(5,'Triggering a generic enrichment pipeline does not explicitly describe code, program, script or shell execution.')
change(6,'Quota consumption tied to resolution suggests interaction but does not explicitly describe network communication.',polarity='uncertain',notes='Proposed rule: operation-linked API quota is uncertain network, not affirmed; destination alone does not prove transport.')
change(7,'Dataset provenance and optional pre-fetched inputs leave retrieval versus supplied data unresolved.',polarity='uncertain',notes='Data-source relationship is explicit; tool retrieval versus supplied rows is unresolved. This is not an automatic inference from computation.')
change(30,'Refunds are part of the described operation; no provider actor or exact state-update mode is explicitly identified.',actor='unknown',mode='unknown',condition='on timeout',notes='Actor attribution and refund state semantics unresolved; do not classify as provider lifecycle solely because it is billing.')
unstated(32,'Broadcasting a transaction is not code/script/program execution under the execute definition.')
change(33,'Use an informative evidence span identifying the transaction and operation.',evidence='Broadcast a signed TRON transaction with automatic energy optimization',notes='Broadcast communication is explicit. External interaction domain is not described; no confirmation of ledger inclusion is claimed.')
change(41,'Every write claim, including denials, requires a write mode.',mode='unknown')
unstated(45,'Weekly updates and a computed momentum score describe freshness/computation, not a claim that this tool retrieves data.')
change(51,'Charging is described without explicit actor; billing is not automatically autonomous provider lifecycle.',actor='unknown',mode='unknown',notes='Charge is explicit when verdict delivered; actor and exact state-write mode are unspecified.')
change(55,'Static inspection of supplied code/configuration is an explicit inspection claim; remote retrieval is unnecessary for read.',needs_review='False',notes='Read includes explicitly inspecting existing caller-supplied material; network remains not_stated.')
change(61,'Fill required mode. The no-rewrite denial is clear and conditional, not ambiguous merely because it is conditional.',mode='unknown',needs_review='False',notes='Denies rewriting this vault when field is absent; not a global write denial.')
change(70,'Returning relevant existing design patterns describes information lookup; lack of source location alone is not uncertainty.',needs_review='False',notes='No network claim follows from returning design patterns.')
change(84,'Any URL and page fetching establish an open domain; hypothetical hidden restrictions must not be assumed.',evidence='for any URL so AI crawlers (ChatGPT, Claude, Perplexity) can index the site cleanly. Fetches the page',needs_review='False',notes='Description explicitly says any URL; no invented hidden allowlist.')
change(88,'Revocation clearly disables credentials but does not resolve whether records or authority are removed versus status changed.',polarity='uncertain',notes='Keep deletion uncertain pending a general revocation rule; a separate modifying write captures explicit revocation.')
change(92,'Saving a key-value pair does not explicitly say whether it creates a new key or replaces an existing one.',mode='unknown',needs_review='True',notes='Write is affirmed; additive versus modifying is unresolved.')
change(96,'Comparison/inspection of existing clauses supports read even when supplied by the caller.',needs_review='False',notes='Inspection of clause content is stated; no claim of fetching it over a network.')
change(107,'Fill required mode for denied write.',mode='unknown')
change(110,'A method and relative API path alone do not establish network transport or a named destination.',polarity='uncertain',target='unspecified',notes='Relative API operation suggests communication; no destination or network transport is explicit.')
change(116,'API method/body syntax suggests interaction, but an explicit network communication verb or transport is absent; domain also remains unspecified.',polarity='uncertain',needs_review='True',notes='Named service identifies destination, not proof of network capability. Apply the same method-only threshold as other API-style descriptions.')
change(117,'Composing a chart from API surfaces does not resolve fetching data versus composing a client-side app specification.',polarity='uncertain',evidence='Build a generic MCP Apps chart from one or more FXMacroData endpoint families',notes='Data use is explicit but acquisition by this tool versus generated app remains unresolved.')
change(121,'API surface composition does not explicitly establish a request by this tool; only-approved wording does establish a bounded collection.',polarity='uncertain',evidence='it only composes approved FXMacroData API surfaces into the comparison chart app',notes='Network capability uncertain; approved surfaces explicitly bound the domain. Do not demand host allowlisting to recognize a bounded collection.')
change(123,'Fill required mode for denied write.',mode='unknown')
change(127,'Registration versus subsequent monitoring is unclear; the description does not explicitly assign monitoring to provider lifecycle.',actor='unknown',notes='Monitoring may be a deferred part of tool service; execution phase and actor are unresolved. Freshness alone is not the evidence.')
change(131,'Do not assume provider attribution or a caller-supplied destination solely from custom endpoints.',actor='unknown',target='unspecified',evidence='real-time monitoring of prices, gas, weather, wallet balances/txs, or custom API endpoints',notes='Subsequent endpoint monitoring suggests communication; actor, phase, destination selection and domain are unresolved.')
change(132,'Explicitly validating existing manifest fields is inspection; supplied input does not prevent read.',needs_review='False',notes='Read of supplied manifest is stated; no external retrieval inferred.')
change(133,'Evidence must include the negation, not only the positive-looking coordinated fragment.',evidence='It never executes plugin code or loads provider secrets.')
change(144,'Use evidence naming the actual search operation, rather than only an instruction to supply text.',evidence='Semantic search INSIDE a fetched record.')
change(150,'A persistent workspace is described, but provisioning versus returning an existing environment is unresolved.',polarity='uncertain',mode='unknown',notes='State creation is plausible, not explicitly established by persistence alone.')
change(153,'Scraping suggests interaction; destination selection is not stated. Uncertainty is not based on hypothetical restrictions.',target='unspecified',notes='Scraping suggests network capability but does not explicitly specify network transport or destination selection; no hidden restrictions assumed.')
change(159,'Relative PATCH path alone does not establish network transport or a named API destination; Pluggy attribution concerns categorization.',polarity='uncertain',target='unspecified',notes='API-style route suggests network; no explicit request to a named host is described.')

added=[]
def add(tid,reason,**kw):
 base=next(r for r in original if r['tool_id']==tid)
 r={k:'' for k in fields};r.update(tool_id=tid,description=base['description']);r.update(kw)
 added.append(r);changes.append({'original_csv_record':None,'tool_id':tid,'effect':r['effect'],'reason':reason,'added_claim':{k:v for k,v in r.items() if k not in ('tool_id','description') and v}})

add('census_v2:13401','Polling import_status is explicitly advice involving another tool; not a current-tool read.',effect='read',polarity='affirmed',scope='batch status',actor='other_tool',evidence='you can poll with import_status',needs_review='False',notes='Other-tool action only; do not aggregate into current-tool effects.')
# Remove the initial placeholder where an attributed claim now exists for the same effect.
rows=[r for r in rows if not (r['tool_id']=='census_v2:13401' and r['effect']=='read' and r['polarity']=='not_stated')]
add('census_v2:21540','Broadcasting submits a transaction: separate state submission from code execution and ledger confirmation.',effect='write',polarity='affirmed',scope='transaction submission',actor='tool',condition='when endpoint is enabled by feature flag',mode='additive',evidence='Broadcast a signed TRON transaction with automatic energy optimization',needs_review='False',notes='Submission only; does not assert successful confirmation on chain.')
add('census_v2:12866','Scoped no-change wording also denies deletion of company records under the broad-denial rule.',effect='delete',polarity='denied',scope='company records',actor='tool',evidence='Does not read or change company records',needs_review='False')
rows=[r for r in rows if not (r['tool_id']=='census_v2:12866' and r['effect']=='delete' and r['polarity']=='not_stated')]
add('census_v2:12702','Explicit checking of supplied source code is read/inspection.',effect='read',polarity='affirmed',scope='supplied source code',actor='tool',evidence='It checks the code against the contract exactly as given.',needs_review='False')
rows=[r for r in rows if not (r['tool_id']=='census_v2:12702' and r['effect']=='read' and r['polarity']=='not_stated')]
add('census_v2:25993','Revoking credentials explicitly changes their validity, independently of whether deletion occurs.',effect='write',polarity='affirmed',scope='API key validity',actor='tool',condition='rotate=true',mode='modifying',evidence='with rotate=true, revokes\nthe existing keys',needs_review='False')
add('census_v2:56462','Recall and forget are recommendations involving separate tools, not effects of this save tool.',effect='read',polarity='affirmed',scope='saved memory',actor='other_tool',evidence='Pair with recall to retrieve later',needs_review='False')
rows=[r for r in rows if not (r['tool_id']=='census_v2:56462' and r['effect']=='read' and r['polarity']=='not_stated')]
add('census_v2:56462','Explicit other-tool deletion advice must not be attributed to the save tool.',effect='delete',polarity='affirmed',scope='saved memory',actor='other_tool',evidence='Pair with recall to retrieve later, forget to delete.',needs_review='False')
rows=[r for r in rows if not (r['tool_id']=='census_v2:56462' and r['effect']=='delete' and r['polarity']=='not_stated')]
add('census_v2:35417','Preserve the explicit scoped denial of arbitrary URL fetching as well as possible approved-surface capability.',effect='network',polarity='denied',scope='arbitrary URLs',actor='tool',target='unspecified',interaction_domain='open',evidence='The tool does not fetch arbitrary URLs or run custom chart code',needs_review='False')
add('census_v2:39151','The whole-row deletion is expressly attributed to another tool.',effect='delete',polarity='affirmed',scope='whole credential row',actor='other_tool',evidence='``forget_credentials``, which wipes the whole row',needs_review='False')
# Record additional attributed actions where a named tool is explicitly assigned an action.
add('census_v2:18830','Explicit lookup action belongs to screen, not the comparison tool.',effect='read',polarity='affirmed',scope='symbols',actor='other_tool',evidence='`screen` finds symbols from a description',needs_review='False')
add('census_v2:74402','Calendar IDs are shown by list_calendars, not this mutation tool.',effect='read',polarity='affirmed',scope='calendar IDs',actor='other_tool',evidence='the ids list_calendars shows',needs_review='False')
rows=[r for r in rows if not (r['tool_id']=='census_v2:74402' and r['effect']=='read' and r['polarity']=='not_stated')]
add('census_v2:21540','Manual fallback explicitly attributes provisioning to a different tool.',effect='write',polarity='affirmed',scope='energy resources',actor='other_tool',condition='if a 503 MAINTENANCE error is received',mode='unknown',evidence='call ensure_resources to\nprovision energy',needs_review='True',notes='Other-tool provisioning; additive versus modifying state unspecified.')
add('census_v2:21540','Manual fallback tells the user/client to broadcast, not the disabled endpoint.',effect='network',polarity='affirmed',scope='TRON transaction broadcast',actor='user',condition='if a 503 MAINTENANCE error is received',target='named_service',interaction_domain='unspecified',evidence='broadcast the transaction with your own TronWeb client',needs_review='True',notes='Separate fallback actor; interaction domain unspecified.')
add('census_v2:26770','Follow-up information lookup explicitly belongs to get_requirement.',effect='read',polarity='affirmed',scope='pattern requirements',actor='other_tool',evidence='follow up with get_requirement on specific pattern_ids',needs_review='False')
add('census_v2:59913','Fetching with a gateway is advice about another tool, not network access by search_within.',effect='read',polarity='affirmed',scope='record content',actor='other_tool',evidence='fetch with the gateway',needs_review='False')

# Group in original tool order and original effect order; retain within-effect distinct claims.
allrows=rows+added
order=list(dict.fromkeys(r['tool_id'] for r in original));eff=['read','write','delete','execute','network']
allrows.sort(key=lambda r:(order.index(r['tool_id']),eff.index(r['effect'])))
for r in allrows:
 if r['polarity']=='not_stated':
  assert all(not r[k] for k in fields if k not in ('tool_id','description','effect','polarity'))
  continue
 assert r['evidence'] and r['evidence'] in r['description'],(r['tool_id'],r['evidence'])
 assert r['actor'] in ('tool','provider','other_tool','user','unknown')
 if r['effect']=='write':assert r['mode'] in ('additive','modifying','mixed','unknown')
 else:assert not r['mode']
 if r['effect']=='network':
  assert r['target'] in ('caller_supplied','named_service','unspecified')
  assert r['interaction_domain'] in ('open','closed','unspecified')
 else:assert not r['target'] and not r['interaction_domain']
 if r['polarity']=='uncertain' or r['actor']=='unknown' or (r['effect']=='network' and r['interaction_domain']=='unspecified'):assert r['needs_review'].lower()=='true'
assert len(order)==30
shutil.copyfile(SRC,OUT/'Menna_Original_Unchanged.csv')
with (OUT/'Menna_Reviewed_Proposals.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(allrows)
(OUT/'Change_Log.json').write_text(json.dumps(changes,ensure_ascii=False,indent=2),encoding='utf-8')
with (OUT/'Change_Log.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['original_csv_record','tool_id','effect','reason','details']);w.writeheader()
 for c in changes:w.writerow({'original_csv_record':c['original_csv_record'] or 'ADDED','tool_id':c['tool_id'],'effect':c['effect'],'reason':c['reason'],'details':json.dumps(c.get('changes',c.get('added_claim')),ensure_ascii=False)})
changed_ids={c['tool_id'] for c in changes}
summary={'source_file':str(SRC),'library_reference':'libfile_dec66d0ca024819193960e8f4a50f36a','source_sha256':hashlib.sha256(raw).hexdigest(),'source_bytes':len(raw),'source_access':'Local working copy; Library read returned no readable content and Library download failed. Local filename and byte size match supplied Library metadata; byte-for-byte equality to Library was not verified.','original_tools':len(order),'original_rows':len(original),'reviewed_rows':len(allrows),'changed_original_rows':sum(c['original_csv_record'] is not None for c in changes),'added_claims':len(added),'tools_with_proposed_changes':len(changed_ids),'evidence_substrings_validated_original':all(r['evidence'] in r['description'] for r in original if r['polarity']!='not_stated'),'reviewed_schema_checks':'passed','original_preserved':(OUT/'Menna_Original_Unchanged.csv').read_bytes()==raw,'review_method':'AI-assisted proposals, not independent human labels or adjudicated ground truth','status':'Await Menna adjudication; Tasneem independent labels pending.'}
(OUT/'Review_Summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=True,indent=2))
