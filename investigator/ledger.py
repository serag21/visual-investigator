"""Experimental reported-evidence ledger. Deterministic constraints, never verified fit."""
from decimal import Decimal, InvalidOperation
import re
from .models import Finding

RULES={
 'dc_adapter': {'required':('voltage','current','polarity','connector_outer','connector_inner','regulated_dc'),
   'source':'https://www.pololu.com/docs/0J71/4.1','scope':'General current capacity rule; not device-specific compatibility.'},
 'filter': {'required':('filter_width','filter_length','filter_depth'),
   'source':None,'scope':'Comparison of reported dimensions only; nominal versus actual size and system requirements remain unknown.'},
 'thread': {'required':('thread_diameter','thread_standard'),
   'source':'https://catalogues.neoperl.net/neoperl-catalogue-2016/0748097001438690204/p21',
   'scope':'Thread families/pitches exist; measured diameter alone does not identify a standard.'}}


def normalized(report):
    value=report['value'].strip().lower()
    if report['unit']=='text':return value
    if not re.fullmatch(r'\d{1,6}(?:\.\d{1,6})?',value):raise ValueError('Use one positive numeric value, without guessed ranges.')
    try: number=Decimal(value)
    except InvalidOperation:raise ValueError('Invalid measurement') from None
    if number<=0:raise ValueError('Measurements must be positive.')
    if report['unit']=='in':number*=Decimal('25.4')
    return str(number.normalize())


def add_reports(existing, additions, pictures):
    result=[dict(r) for r in existing]
    for report in additions:
        report=dict(report);normalized(report)
        if report.get('picture_id') and report['picture_id'] not in pictures:raise ValueError('Choose an existing evidence photo.')
        previous=report.pop('replaces_id',None)
        if previous:
            old=next((r for r in result if r['id']==previous),None)
            if not old or old.get('superseded_by') or (old['subject'],old['name'])!=(report['subject'],report['name']):
                raise ValueError('A correction must refer to an active report of the same item and specification.')
        report.update(id=f'E{len(result)+1}',kind='confirmed_user_report')
        if previous:old['superseded_by']=report['id']
        result.append(report)
        if len(result)>40:raise ValueError('This investigation has reached 40 specification reports.')
    return result


def decision_record(goal,reports):
    if goal not in RULES:return None
    rules=RULES[goal]; active=[r for r in reports if not r.get('superseded_by')]
    conflicts=[]; rows=[]; missing=[]
    for name in rules['required']:
        sides={side:[r for r in active if r['name']==name and r['subject']==side and r['value'].lower().strip() not in ('unknown','unverified','?','not sure','not known')] for side in ('original','candidate')}
        if name=='current':
            requirements=[r for r in sides['original'] if r.get('current_is_requirement',False)]
            if requirements:sides['original']=requirements
        length=name not in ('voltage','current','polarity','regulated_dc','thread_standard')
        def internal_conflict(rs):
            bases={r.get('basis','unspecified') for r in rs} if length else {'rating'}
            return any(len({normalized(r) for r in rs if not length or r.get('basis','unspecified')==basis})>1 for basis in bases)
        internal=any(internal_conflict(rs) for rs in sides.values())
        if internal:
            conflicts.append(name); status='conflicting_reports'
        elif not all(sides.values()):status='missing';missing.append(name)
        else:
            pairs=[(l,r) for l in sides['original'] for r in sides['candidate']
                   if not length or (l.get('basis','unspecified')!='unspecified' and l.get('basis')==r.get('basis'))]
            left,right=pairs[0] if pairs else (sides['original'][0],sides['candidate'][0])
            # Reject mixing dimensions with other units or incompatible unit classes.
            units=lambda r:'length' if r['unit'] in ('mm','in') else r['unit']
            if units(left)!=units(right):status='unit_conflict';conflicts.append(name)
            elif length and (left.get('basis','unspecified')=='unspecified' or left.get('basis')!=right.get('basis')):
                status='missing';missing.append(name)
            elif name=='current' and goal=='dc_adapter':
                regulated=all(any(r['subject']==side and r['name']=='regulated_dc' and r['value'].lower()=='yes' for r in active) for side in ('original','candidate'))
                status=('reported_match' if Decimal(normalized(right))>=Decimal(normalized(left)) else 'reported_mismatch') if regulated else 'missing'
                if not regulated:missing.append('regulated_dc')
                if status=='reported_mismatch' and not left.get('current_is_requirement',False):
                    # Old supply capacity is not the device's actual draw or minimum requirement.
                    status='missing';missing.append('device_current_requirement')
            elif name=='thread_standard' and normalized(left)!=normalized(right):
                status='missing';missing.append(name)  # Text differences are not proof of mechanical mismatch.
            else:status='reported_match' if all(normalized(l)==normalized(r) for l,r in pairs) else 'reported_mismatch'
        rows.append({'name':name,'status':status,'reports':sides})
    mismatch=[r['name'] for r in rows if r['status']=='reported_mismatch']
    # A conflicting report takes precedence over a tempting downstream numerical conclusion.
    decision='conflicting_evidence' if conflicts else 'mismatch' if mismatch else 'unverified'
    return {'goal':goal,'decision':decision,'conflicts':conflicts,'mismatches':mismatch,'missing':sorted(set(missing)),
            'constraints':rows,'source':rules['source'],'source_scope':rules['scope'],
            'verification':'User-confirmed reports, not independently verified specifications. Matching these fields never certifies overall fit.'}


def constrain_finding(finding:Finding,record):
    if not record or finding.status=='safety_stop':return finding
    decision=record['decision']
    if decision in ('conflicting_evidence','mismatch'):
        # A model interpretation must not contradict the local evidence decision anywhere in the card.
        finding.facts=[];finding.interpretations=[];finding.compatibility.constraints=[]
        finding.unknowns=record['missing'][:6]
    if decision=='conflicting_evidence':
        names=', '.join(record['conflicts'])
        finding.answer=f'Your reports conflict for {names}. Keep the candidate decision open until you check which report is correct.'
        finding.status='needs_evidence';finding.next_question=f'Can you confirm the {record["conflicts"][0].replace("_"," ")} for the correct item?'
        finding.next_action='Correct the conflicting evidence report; the earlier value will stay in the history.'
        finding.compatibility.decision='unverified'
    elif decision=='mismatch':
        finding.answer='The reported '+', '.join(record['mismatches']).replace('_',' ')+' conflicts with the candidate. Do not choose this candidate on the current evidence.'
        finding.status='concluded';finding.next_question='';finding.next_action='Use the conflicting requirement to rule out this candidate; an exact replacement still needs verification.'
        finding.compatibility.decision='mismatch'
    else:
        finding.compatibility.decision='unverified'
        positive=r'\b(?:safe to use|will work|compatible|fits|buy this)\b'
        if re.search(positive,' '.join([finding.answer,finding.next_action,*finding.interpretations]),re.I):
            finding.answer='The recorded reports do not establish overall compatibility. Review the missing constraints and device-specific requirements before choosing a replacement.'
            finding.status='needs_evidence'
            finding.interpretations=[];finding.compatibility.constraints=[]
            finding.next_action='Check the missing constraints against documentation for the exact device before choosing a replacement.'
    finding.compatibility.summary=record['verification'][:350]
    return finding


def capture_action(question):
    if not question:return None
    if re.search(r'photo|picture|label|marking',question,re.I):kind='photo'
    elif re.search(r'measur|diameter|width|length|pitch|dimension',question,re.I):kind='measurement'
    else:kind='context'
    return {'kind':kind,'instruction':question,'verification':'AI-requested evidence; usefulness has not been independently verified.'}


def local_finding(record):
    needs_current=record and record['decision']=='unverified' and 'device_current_requirement' in record['missing']
    if not record or (record['decision'] not in ('conflicting_evidence','mismatch') and not needs_current):return None
    base=Finding.model_validate({'title':'Reported evidence check','answer':'Review the reported constraints.',
        'status':'needs_evidence','facts':[],'interpretations':[],'unknowns':record['missing'],
        'next_question':'','next_action':'','risk':'caution',
        'compatibility':{'decision':'unverified','summary':'Reported evidence only.','constraints':[]}})
    if needs_current:
        base.answer="The old adapter's maximum current rating does not establish the device's required current. A lower candidate rating alone is not enough to decide; compatibility remains unverified."
        base.next_question='What minimum current does the device itself require according to its own label or manual?'
        base.next_action='Check the device documentation; do not power or open equipment to obtain this information.'
    return constrain_finding(base,record)
