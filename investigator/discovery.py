"""Check proposed public manufacturer pages; NOT a search engine or fit oracle.

Untrusted model leads are hidden until a real official document is retrieved and
its title/product metadata matches. No paid API, image upload, or query scraping.
"""
from datetime import datetime, timezone
import hashlib
import html
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlparse, urlencode

BRANDS={
    'govee':('us.govee.com','www.govee.com','govee.com'),
    'anker':('www.anker.com','anker.com'),
    'logitech':('www.logitech.com','logitech.com'),
    'belkin':('www.belkin.com','belkin.com'),
    'nintendo':('www.nintendo.com','nintendo.com'),
    'knipex':('www.knipex.com','www.knipex-tools.com'),
    'ikea':('www.ikea.com',),
}
HOSTS={h for hosts in BRANDS.values() for h in hosts}
AGENT='VisualInvestigatorBeta/0.4'
ROBOTS={}


def safe_url(url,check_dns=True):
    if not isinstance(url,str) or len(url)>350:raise ValueError('Invalid reference')
    p=urlparse(url)
    if (p.scheme!='https' or p.hostname not in HOSTS or p.username or p.password or
        p.port not in (None,443) or p.query or p.fragment or
        not p.path.startswith(('/products/','/product/','/en-us/products/','/en-us/shop/p/','/en-us/store/products/','/us/store/products/','/us/en/p/','/p/')) or
        not re.fullmatch(r'/[A-Za-z0-9/_%.\-]+',p.path) or '%' in p.path or '..' in p.path):
        raise ValueError('Use a supported official product page, without tracking parameters.')
    if check_dns:
        ips=socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
        if not ips or any(not ipaddress.ip_address(row[4][0]).is_global for row in ips):raise ValueError('Public hosts only')
    return url


class ProductRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        safe_url(newurl)
        if urlparse(newurl).hostname!=urlparse(req.full_url).hostname:raise ValueError('Cross-host redirects are not followed')
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def robots_allow(host,path):
    cached=ROBOTS.get(host)
    if cached and time.monotonic()-cached[0]<900:return cached[1].can_fetch(AGENT,path)
    req=urllib.request.Request('https://'+host+'/robots.txt',headers={'User-Agent':AGENT})
    # Do not follow robots redirects to arbitrary hosts.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,*a,**kw):return None
    try:
        with urllib.request.build_opener(NoRedirect()).open(req,timeout=3) as response:
            raw=response.read(64001)
            if len(raw)>64000:return False
        lines=raw.decode('utf-8','replace').splitlines()
    except urllib.error.HTTPError as exc:
        if exc.code==404:lines=['User-agent: *','Allow: /']
        else:return False
    except (OSError,ValueError,urllib.error.URLError):return False
    parser=urllib.robotparser.RobotFileParser();parser.parse(lines)
    if len(ROBOTS)>=32:ROBOTS.clear()
    ROBOTS[host]=(time.monotonic(),parser)
    return parser.can_fetch(AGENT,path)


def page_metadata(document):
    match=re.search(r'<title\b[^>]*>(.*?)</title>',document,re.I|re.S)
    title=html.unescape(re.sub('<[^>]+>',' ',match[1])).strip() if match else ''
    products=[]
    def walk(value,depth=0):
        if depth>12:return
        if isinstance(value,list):
            for item in value[:40]:walk(item,depth+1)
        elif isinstance(value,dict):
            kind=value.get('@type',[])
            if kind=='Product' or isinstance(kind,list) and 'Product' in kind:products.append(value)
            for key in ('@graph','mainEntity','itemListElement','item'):
                if key in value:walk(value[key],depth+1)
    for script in re.findall(r'<script\b[^>]*type=[\'\"]application/ld\+json[\'\"][^>]*>(.*?)</script>',document,re.I|re.S)[:20]:
        try:walk(json.loads(script))
        except (ValueError,RecursionError):continue
    return title,products


def check_candidate(candidate):
    value=candidate.model_dump() if hasattr(candidate,'model_dump') else candidate
    result={'candidate_name':value['name'],'status':'unavailable',
            'verification':'Possible product family, not verified identity or compatibility.',
            'retrieved_at':datetime.now(timezone.utc).isoformat()}
    try:
        url=safe_url(value['manufacturer_url']);p=urlparse(url)
        if not robots_allow(p.hostname,p.path):result['status']='retrieval_not_permitted';return result
        req=urllib.request.Request(url,headers={'User-Agent':AGENT,'Accept':'text/html'})
        with urllib.request.build_opener(ProductRedirect()).open(req,timeout=5) as response:
            if 'text/html' not in response.headers.get('Content-Type',''):return result
            raw=response.read(2_000_001)
        # The measured Govee page is 1.23 MB; retain a strict two-megabyte cap.
        if len(raw)>2_000_000:result['status']='document_too_large';return result
        title,products=page_metadata(raw.decode('utf-8','replace'))
        name=value['name'].lower()
        terms=set(re.findall(r'[a-z0-9]{3,}',name))-{'with','and','the','for','govee','anker','logitech','belkin','nintendo','knipex','ikea'}
        model_codes=re.findall(r'\b[a-z]+\d[a-z0-9-]{2,}\b',name)
        matched=None
        for product in products:
            text=' '.join(str(product.get(k,'')) for k in ('name','description','model','sku')).lower()
            if len(terms.intersection(set(re.findall(r'[a-z0-9]{3,}',text))))>=min(2,len(terms)) and terms and all(code in text for code in model_codes):
                matched=product;break
        if matched is None:
            result.update(status='product_metadata_mismatch',document_sha256=hashlib.sha256(raw).hexdigest());return result
        description=html.unescape(re.sub('<[^>]+>',' ',str(matched.get('description',''))))
        result.update(status='retrieved',url=url,publisher=p.hostname,title=str(matched.get('name') or title)[:160],
            excerpt=' '.join(description.split())[:600],document_sha256=hashlib.sha256(raw).hexdigest(),
            hypothesis=value['why_plausible'],distinguishing_evidence=value['distinguishing_evidence'])
    except (ValueError,OSError,urllib.error.URLError,TypeError,KeyError):pass
    return result


def discover(finding):
    # This deliberately makes no claim to have searched all products/the web.
    leads=[];seen=set()
    for c in finding.candidate_hypotheses:
        if c.manufacturer_url in seen:continue
        seen.add(c.manufacturer_url);leads.append(check_candidate(c))
        if len(leads)==2:break
    text=finding.title+' '+finding.answer
    brands=[brand for brand in BRANDS if re.search(r'\b'+brand+r'\b',text,re.I)]
    query=' '.join(re.findall(r'[A-Za-z0-9-]+',finding.title))[:100]
    return {'mode':'checked_model_leads','candidates':leads,
            'coverage':'Proposed manufacturer pages checked; no comprehensive web or inventory search. Google Search grounding is unavailable on this Free Tier.',
            'search_handoff':{'label':'Search the web yourself','url':'https://www.google.com/search?'+urlencode({'q':query+' official manufacturer'})},
            'brand_sites':[{'brand':b,'url':'https://'+BRANDS[b][0]+'/'} for b in brands],
            'verification':'A real source can describe a candidate without identifying your photographed item. No prices, stock or fit verified.'}
