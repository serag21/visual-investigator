"""Small, explicit source library. No arbitrary URLs, search API, images, or model calls."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import html
import re
import urllib.request
from urllib.parse import urlparse


SOURCES = (
    {"id":"locking-pliers", "title":"Curved jaw locking pliers — Fast Release", "publisher":"IRWIN Tools",
     "url":"https://www.irwin.eu/tools/pliers-and-wrenches/curved-jaw-locking-pliers-fast-release",
     "expected_title":"curved jaw locking", "terms":("locking pliers","vise-grip","vise grips"),
     "kind":"manufacturer product-family reference; example variants, not verification of the photographed model or safe use"},
    {"id": "adapter", "title": "Power supplies", "publisher": "Adafruit",
     "url": "https://learn.adafruit.com/power-supplies?view=all", "expected_title": "power supplies",
     "terms": ("adapter", "power supply", "voltage", "polarity"), "kind": "technical explanation"},
    {"id": "usb", "title": "USB cable and connector documentation", "publisher": "USB-IF",
     "url": "https://www.usb.org/cable_connector", "expected_title": "cable", "terms": ("usb",), "kind": "standards documentation"},
    {"id": "displayport", "title": "How to choose a DisplayPort cable", "publisher": "VESA / DisplayPort",
     "url": "https://www.displayport.org/how-to-choose-a-displayport-cable-and-not-get-a-bad-one/", "expected_title": "displayport cable",
     "terms": ("displayport", "display connector"), "kind": "standards-organization guidance; cable capability needs certification"},
    {"id": "circlip", "title": "Circlip pliers: choosing the right type", "publisher": "KNIPEX",
     "url": "https://blog.knipex.com/en/en/blog/aj-0", "expected_title": "circlip", "terms": ("circlip", "snap ring", "retaining ring"), "kind": "manufacturer explanation"},
    {"id": "circlip-product", "title": "49 11 A0 external precision snap-ring pliers", "publisher": "KNIPEX Tools",
     "url": "https://www.knipex-tools.com/products/snap-ring-pliers/precision-snap-ring-pliers-external/external-precision-snap-ring-pliers/4911A0",
     "expected_title": "49", "terms": ("circlip", "snap ring"), "kind": "real product example; fit NOT established"},
    {"id": "washer", "title": "Cleaning a washing-machine pump filter", "publisher": "Samsung",
     "url": "https://www.samsung.com/au/support/home-appliances/how-to-clean-the-pump-filter/",
     "expected_title": "pump filter", "terms": ("washer", "washing machine", "pump filter"), "kind": "manufacturer instructions; check your exact model"},
    {"id": "mold", "title": "Mold, moisture and your home", "publisher": "US EPA",
     "url": "https://www.epa.gov/mold/brief-guide-mold-moisture-and-your-home",
     "expected_title": "mold", "terms": ("mold", "mould", "stain", "moisture", "efflorescence"), "kind": "public-agency guidance; does NOT identify a photographed material"},
)


class Paragraphs(HTMLParser):
    def __init__(self):
        super().__init__(); self.skip = 0; self.parts = []; self.current = []; self.capture=False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip += 1
        if tag in ('p','li'):
            self.current=[];self.capture=True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav", "footer", "header"):
            self.skip = max(0, self.skip-1)
        if tag in ("p", "li"):
            text = " ".join(" ".join(self.current).split())
            if len(text) >= 45:
                self.parts.append(text)
            self.current = []
            self.capture=False

    def handle_data(self, data):
        if not self.skip and self.capture:
            self.current.append(data)


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlparse(newurl).scheme != "https" or urlparse(newurl).hostname != urlparse(req.full_url).hostname:
            raise ValueError("Cross-host redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def select_sources(text):
    lower = text.lower()
    return [dict(s) for s in SOURCES if any(re.search(r"\b"+re.escape(term)+r"\b", lower) for term in s["terms"])][:3]


def fetch_source(source):
    """Only fetch a source selected from the fixed catalog; never accept user URLs."""
    canonical = next((s for s in SOURCES if s["id"] == source.get("id")), None)
    if canonical is None or source.get("url") != canonical["url"]:
        raise ValueError("Unknown reference")
    result = {k: v for k, v in canonical.items() if k not in ("terms", "expected_title")}
    result.update(retrieved_at=datetime.now(timezone.utc).isoformat(), status="unavailable", excerpt="")
    try:
        request = urllib.request.Request(canonical["url"], headers={"User-Agent": "VisualInvestigator-local-reference-prototype/0.1"})
        with urllib.request.build_opener(SameHostRedirect()).open(request, timeout=6) as response:
            if "text/html" not in response.headers.get("Content-Type", ""):
                raise ValueError("Not an HTML document")
            body = response.read(250_001)
            if len(body) > 250_000:
                raise ValueError("Reference exceeds bounded retrieval size")
        document = body.decode("utf-8", errors="replace")
        title_match = re.search(r"<title\b[^>]*>(.*?)</title>", document, re.I | re.S)
        title = html.unescape(title_match[1]).strip() if title_match else ""
        if canonical["expected_title"] not in title.lower():
            result.update(status="title_mismatch", document_title=title[:200], document_sha256=hashlib.sha256(body).hexdigest())
            return result
        parser = Paragraphs(); parser.feed(document)
        substantive=parser.parts
        relevant = [p for p in substantive if any(t in p.lower() for t in canonical["terms"])]
        excerpt = "\n\n".join((relevant or substantive)[:4])[:1600]
        result.update(status="retrieved" if excerpt else "no_readable_excerpt", excerpt=excerpt, document_title=title[:200],
                      document_sha256=hashlib.sha256(body).hexdigest(), bytes_received=len(body))
    except Exception as exc:
        # No raw HTTP bodies, arbitrary URLs or external exception messages in the UI.
        result["failure_kind"] = type(exc).__name__
    return result


def research(text):
    return {"coverage": "Small curated official-source library, not a web or inventory search.",
            "verification": "Document excerpts do not verify photo identity, exact fit, price or availability. Check the linked source and your exact model.",
            "sources": [fetch_source(s) for s in select_sources(text)]}
