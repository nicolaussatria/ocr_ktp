"""Business-card roles, contacts and layout-aware evidence resolution.

Layout cues are deliberately transparent heuristics, not a trained entity model.
They never reconstruct a person's name or contact details from a domain or logo.
"""
import re
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from statistics import median
from urllib.parse import urlsplit

import numpy as np
import phonenumbers
from email_validator import EmailNotValidError, validate_email

from ..schemas import Candidate, Evidence, FieldResult, Span
from .common import Observation, Parsed, canonical_street, label_word, normalize_text, normalized

SCALAR_FIELDS = ("full_name", "company", "company_alias", "job_title", "address")
LIST_FIELDS = ("emails", "phones", "websites", "social_handles")
EMAIL_RE = re.compile(r"[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9.-]+\.[A-Z]{2,}(?![\w-])", re.I)
WEB_RE = re.compile(r"(?<![@\w])(?:https?://|www\.)[^\s|,;]+", re.I)
BARE_WEB_RE = re.compile(r"(?<![@\w.])[A-Z0-9-]+(?:\.[A-Z0-9-]+)*\.[A-Z]{2,}(?![\w-])(?:/[^\s|,;]*)?", re.I)
COMPANY_RE = re.compile(
    r"^(?:(?:PT|CV|UD|TBK)\.?(?:\s+|(?=[A-Z][a-z]))|COMPANY(?:\s*NAME)?$)|"
    r"\b(?:CO|CORP|CORPORATION|COMPANY|GROUP|LTD|LIMITED|INC|LLC|PTE|TBK|GMBH)\.?$", re.I
)
# A role names what one person does. ROLE_RE holds the words that can only be a person's
# role; JOB_RE adds the departments ("Sales", "Marketing") that stand in for one.
ROLE_WORDS = (
    r"manager|manajer|director|direktur|engineer|developer|programmer|konsultan|consultant|"
    r"founder|owner|pemilik|CEO|CTO|CFO|COO|CMO|CIO|supervisor|accountant|akuntan|auditor|"
    r"architect|arsitek|designer|kepala|pimpinan|wakil|agen|agent|specialist|analyst|"
    r"commissioner|komisaris|officer|president|chairman|professor|lecturer|dosen|realtor|"
    r"executive|administrator|coordinator|koordinator|secretary|sekretaris|assistant|asisten|"
    r"advisor|adviser|penasihat|representative|technician|teknisi|trainer|notaris|lawyer|"
    r"advokat|pengacara|staff|staf|head\s+of|(?:team|tech|technical|project|group)\s+lead(?:er)?"
)
ROLE_RE = re.compile(rf"\b(?:{ROLE_WORDS})\b", re.I)
# Capitals only: "gm" inside a sentence is not a General Manager.
ROLE_ABBREVIATION_RE = re.compile(r"\b(?:GM|VP|SVP|AVP|EVP)\b")
JOB_RE = re.compile(rf"\b(?:{ROLE_WORDS}|engineering|sales|marketing)\b|(?-i:\b(?:GM|VP|SVP|AVP|EVP)\b)", re.I)
# What a company offers. A line that also names a role ("Senior Solutions Consultant",
# "Customer Service Officer") is the role; a dealership never is.
SERVICE_RE = re.compile(
    r"\b(?:authorized|dealer|spare\s*parts|services?|solutions?|supplier|consultation|"
    r"business intelligenc?e?|business intelligent|enterprise resource planning|"
    r"management systems?|financial systems?|planning & budgeting)\b", re.I
)
TRADE_RE = re.compile(r"\b(?:authorized|dealer|distributor|supplier|spare\s*parts)\b", re.I)
OFFICE_RE = re.compile(
    r"^(?:(?:head|branch|representative|sales(?:\s*&\s*marketing)?)\s+)?office\s*:?$|"
    r"^kantor(?:\s+(?:pusat|cabang|perwakilan))?\s*:?$", re.I
)
AFFILIATION_RE = re.compile(r"^(?:a\s+)?(?:member|part)\s+of\b", re.I)
TITLE_MODIFIER_RE = re.compile(
    r"^(?:(?:senior|junior|regional|national|area|account|relationship|information|technology|"
    r"business|development|technical|project|product|operational|operations|&)[\s/-]*)+$", re.I
)
LOCALITY_RE = re.compile(
    r"^(?:indonesia|jakarta|tangerang|bekasi|bogor|depok|bandung|surabaya|semarang|"
    r"yogyakarta|medan|bali|jawa\s+(?:barat|tengah|timur)|dki|banten|kota|kabupaten|"
    r"kec(?:amatan)?\.?|kel(?:urahan)?\.?|desa)\b", re.I
)
ADDRESS_RE = re.compile(
    r"^(?:alamat\s*:|address\s*:|j[lIi1]\.?\s|jalan\s|gg\.?\s|gang\s|komp(?:lek)?\.?\s|"
    # "JI.Gatot Subroto": a street prefix glued to the name, but not "ji.andreas@..." or "jl.co.id".
    r"j[lIi1]\.(?=[A-Z][a-z])(?!\S*@)(?!\S*\.[A-Z]{2,}\b))|"
    r"\b(?:street|road|avenue|building|gedung|boulevard|floor|lantai|tower|wisma|ruko|"
    r"perkantoran|kompleks|komplek|kav(?:ling)?|blok|suite)\b|"
    r"\s@\s*[^@]+\b(?:city|plaza|tower)\b|"
    r"\b(?:st|rd|ave|blvd)\.(?:\s|,|$)|\bRaya\b|\bNo\.?\s*\d", re.I
)
LABEL_WORDS = {
    "full_name": ("NAMA", "NAME"),
    "company": ("PERUSAHAAN", "COMPANY"),
    "job_title": ("JABATAN", "TITLE"),
    "address": ("ALAMAT", "ADDRESS"),
}
LABELED = re.compile(
    r"^(?:"
    + "|".join(
        f"(?P<{key}>{'|'.join(label_word(word) for word in words)})"
        for key, words in LABEL_WORDS.items()
    )
    + r")\s*:\s*(?P<value>.+)$",
    re.I,
)
# Indonesian and English contact labels. "Telepon", "Telp" and "Kontak" are common on
# local cards and must not make an otherwise clear number unreadable.
PHONE_LABEL_NAME = (
    r"(?:no\.?\s*)?(?:telepon|telp|tlp|tel(?:ephone)?|phone|mobile|mob|handphone|hp|wa|whatsapp|"
    r"ponsel|seluler|fax(?:imile)?|faks|cell|office|kantor|direct|kontak|contact|ph|t|m|f|p)"
)
# What the label in front of a number says it is. "Kontak" says nothing.
PHONE_KINDS = (
    ("fax", re.compile(r"^(?:no\.?\s*)?(?:fax(?:imile)?|faks|f)\b", re.I)),
    ("mobile", re.compile(r"^(?:no\.?\s*)?(?:mobile|mob|handphone|hp|wa|whatsapp|cell|ponsel|seluler|m)\b", re.I)),
    ("landline", re.compile(r"^(?:no\.?\s*)?(?:telepon|telp|tlp|tel(?:ephone)?|phone|ph|office|kantor|direct|t|p)\b",
                            re.I)),
)
PHONE_PREFIX = PHONE_LABEL_NAME + r"(?:\s*[:.]\s*|\s+)(?=[+\d(])"
PHONE_LABEL = re.compile(r"^" + PHONE_PREFIX, re.I)
INLINE_PHONE_LABEL = re.compile(r"(?<!\S)" + PHONE_PREFIX, re.I)
CONTACT_LABEL_ONLY = re.compile(r"^(?:" + PHONE_LABEL_NAME + r"|e(?:mail)?|w(?:ebsite)?)\s*[:.]?$", re.I)
PHONE_ONLY = re.compile(r"^[+\d(][\d\s()+.\-]*(?:\s*(?:ext\.?|ex|x|extension)\s*\d+)?$", re.I)
SOCIAL_RE = re.compile(r"^(?:(?:ig|instagram|twitter|tiktok|x)\s*:\s*)?(@[\w.]+)$", re.I)
PLACEHOLDER_RE = re.compile(r"^(?:company(?:\s*name)?|lorem\s*ipsum|your\s+(?:name|company|title))$", re.I)
# A pictogram in front of a contact line is read as whatever glyph it resembles: a
# handset as "白", a globe as "回". One such glyph next to Latin print is the pictogram.
ICON = r"[\u2190-\u2BFF\u2E80-\u9FFF\uF900-\uFAFF\U0001F000-\U0001FAFF]"
LEADING_ICON_RE = re.compile(rf"^{ICON}(?!{ICON})\s*(?=[\x21-\x7E])")
TRAILING_ICON_RE = re.compile(rf"(?<=[\x21-\x7E])\s*(?<!{ICON}){ICON}$")
EDGE_MARKS = " :;|•·☎✉⌂"
# A domain printed without "www." or a label is a website when it is a name with a public
# ending and that name is the host of an email address printed on the same card
# ("contoh.net.id" beside "@contoh.co.id"). The ending alone is not enough: an address
# whose "@" was read as a letter is domain-shaped too ("rina.wocontoh.co.id"), and
# Indonesian degrees are written like domains ("S.Kom", "S.Si", "A.Md", "M.Sc").
PUBLIC_SUFFIX_RE = re.compile(
    r"\.(?:(?:co|net|or|ac|go|web|my|sch|biz|desa)\.id|com\.(?:sg|my|au|cn|hk|tw|vn|ph)|"
    r"co\.(?:uk|jp|kr|th|in|nz)|com|net|org|id|io|co|asia|info|biz|app|dev|tech|online|store|"
    r"shop|site|cloud|xyz|sg|my|au|uk|jp|cn)$", re.I
)
PUBLIC_LABEL_MIN = 3
# Mailboxes and mail hosts that name no person and no company.
SHARED_MAILBOX = frozenset(
    "info sales marketing admin administrator support cs contact hello hi office hr hrd finance "
    "accounting billing service services customer customercare care help helpdesk enquiry inquiry "
    "mail email order orders purchasing procurement corporate secretary sekretariat humas legal "
    "noreply webmaster it team business general recruitment career careers jobs press media pr "
    "partnership reservation booking cso cc".split()
)
FREE_MAIL = frozenset(
    "gmail googlemail yahoo ymail rocketmail hotmail outlook live msn icloud me mac aol proton "
    "protonmail pm mail gmx yandex qq naver".split()
)
# The registrable name of a host is what stands before these.
DOMAIN_CATEGORY = frozenset("co com net org or ac go gov web my sch biz mil edu desa".split())
# What a company adds to its own name in a domain: "contohcorp", "abc-indonesia".
DOMAIN_FILLER = ("indonesia", "indo", "id", "group", "corp", "global", "tech", "digital", "online",
                 "official", "international", "intl", "asia")
# Characters a logo mark is read as when it is taken for print: thin upright strokes.
STROKES = frozenset("iIl1|!.:")
# The same glyph, or nearly: a capital I, a lowercase l and the digit 1; O and zero.
LOOKALIKE_FOLD = str.maketrans({"l": "i", "1": "i", "|": "i", "0": "o"})


# Two boxes of one printed row are of one size; a box this many times taller is not print
# of that row.
ROW_MAX_SCALE = 2.5


@dataclass
class Line:
    text: str
    spans: list[Span]

    @property
    def x(self):
        return min(s.x for s in self.spans)

    @property
    def y(self):
        return min(s.y for s in self.spans)

    @property
    def right(self):
        return max(s.right for s in self.spans)

    @property
    def height(self):
        return median(s.height for s in self.spans)

    @property
    def center(self):
        return (self.x + self.right) / 2


def _without_icon(text: str) -> str:
    return TRAILING_ICON_RE.sub("", LEADING_ICON_RE.sub("", text.strip()))


def _text(spans):
    return " ".join(_without_icon(s.text) for s in spans).strip(EDGE_MARKS)


def _role(text: str) -> bool:
    """Whether a line states one person's role rather than what the company offers."""
    if not JOB_RE.search(text) or TRADE_RE.search(text):
        return False
    return not SERVICE_RE.search(text) or bool(ROLE_RE.search(text) or ROLE_ABBREVIATION_RE.search(text))


def _lines(spans):
    """Do not fuse distant columns just because their baselines coincide."""
    lines = []
    groups = []
    for span in sorted(spans, key=lambda s: (s.center_y, s.x)):
        if not span.text.strip():
            continue
        match = next((g for g in reversed(groups)
                      if abs(span.center_y - median(s.center_y for s in g))
                      <= 0.42 * min(span.height, median(s.height for s in g))), None)
        if match is None:
            groups.append([span])
        else:
            match.append(span)
    for row in groups:
        row.sort(key=lambda s: s.x)
        group = []
        for span in row:
            gap = span.x - group[-1].right if group else 0
            label = bool(group and re.fullmatch(r"(?:name|nama|company|perusahaan|title|jabatan|address|alamat)\s*:",
                                               _text(group) + ":", re.I))
            def contact_like(text):
                return bool("@" in text or WEB_RE.search(text) or PHONE_LABEL.match(text)
                            or CONTACT_LABEL_ONLY.fullmatch(text.strip())
                            or BARE_WEB_RE.fullmatch(text.strip()) or PHONE_ONLY.fullmatch(text.strip(" :;|")))
            separate_role = group and contact_like(span.text) != contact_like(_text(group))
            separate_noise = group and abs(span.score - min(s.score for s in group)) > 0.3 and gap > span.height / 2
            # A large brand beside "PT ..." is a separate column even when its
            # oversized box leaves only a small gap to the legal company name.
            separate_company = (group and COMPANY_RE.search(span.text)
                                and not COMPANY_RE.search(_text(group)))
            # A logo mark read as a few letters stands beside the print, several rows tall.
            separate_scale = group and (max(group[-1].height, span.height)
                                        > ROW_MAX_SCALE * min(group[-1].height, span.height))
            if group and (gap > 2.0 * min(group[-1].height, span.height) or separate_role
                          or separate_noise or separate_company or separate_scale) and not label:
                lines.append(Line(_text(group), group))
                group = []
            group.append(span)
        if group:
            lines.append(Line(_text(group), group))
    return sorted(lines, key=lambda line: (line.y, line.x))


def contact_text(text: str) -> bool:
    """A line that could hold an email, a web or social address, or a phone number.

    Word breaks are never re-derived for these: a gap beside an "@" or a dot is not a
    break. A street line is not a contact even with a number or a glued "Jl." in it.
    """
    text = _without_icon(normalize_text(text)).strip(EDGE_MARKS)
    if EMAIL_RE.search(text) or WEB_RE.search(text) or BARE_WEB_RE.fullmatch(text):
        return True
    if ADDRESS_RE.search(text):
        return False
    return bool("@" in text or "/" in text or WEB_RE.search(text) or BARE_WEB_RE.search(text)
                or PHONE_LABEL.match(text) or re.search(r"\d", text))


def _website(value: str) -> tuple[str, list[str]]:
    value = value.rstrip(".,;)")
    normalized = value if re.match(r"^https?://", value, re.I) else "https://" + value
    try:
        parsed = urlsplit(normalized)
        host = parsed.hostname
        if not host or "." not in host or parsed.username or parsed.password or parsed.port:
            return value, ["invalid_website"]
        if not all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", p) for p in host.split(".")):
            return value, ["invalid_website"]
        return normalized, []
    except ValueError:
        return value, ["invalid_website"]


def _plain_site(value: str) -> str | None:
    """The name of a host that is just a name and a public ending, else None."""
    host = re.sub(r"^https?://", "", value, flags=re.I).split("/")[0].lower()
    ending = PUBLIC_SUFFIX_RE.search(host)
    name = host[:ending.start()] if ending else ""
    return name if len(name) >= PUBLIC_LABEL_MIN and "." not in name else None


def _shared_area_code(lead, digits: str) -> str | None:
    """The number a card means by "(021) 5551234, 5551235": the second subscriber number
    under the area code of the first. Only for a landline, only when the second has
    exactly as many digits as the first's subscriber number, and only when the result is
    a valid number; anything else stays as printed, for review."""
    if phonenumbers.number_type(lead) not in (phonenumbers.PhoneNumberType.FIXED_LINE,
                                              phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE):
        return None
    national = phonenumbers.national_significant_number(lead)
    area = phonenumbers.length_of_geographical_area_code(lead)
    if not area or len(digits) != len(national) - area:
        return None
    try:
        number = phonenumbers.parse(f"+{lead.country_code}{national[:area]}{digits}", None)
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_valid_number(number):
        return None
    return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)


def _phone_kind(printed: str | None, number) -> str | None:
    """mobile, landline or fax. The number itself tells a mobile from a landline (in
    Indonesia every 08 number is a mobile); only the label tells a fax line from a
    telephone line. Where the number cannot tell, the label decides, or nothing does."""
    numbering = None if number is None else phonenumbers.number_type(number)
    if numbering == phonenumbers.PhoneNumberType.MOBILE:
        return "mobile"
    if numbering == phonenumbers.PhoneNumberType.FIXED_LINE:
        return "fax" if printed == "fax" else "landline"
    return printed


def _phones(text, region, shared=True):
    """(value, issues, kind) for each number on one printed line."""
    label = PHONE_LABEL.match(text)
    labeled = bool(label)
    printed = next((kind for kind, pattern in PHONE_KINDS if pattern.match(label.group())), None) if label else None
    body = PHONE_LABEL.sub("", text)
    # Commas, pipes, semicolons and slashes separate numbers; spaces group digits.
    pieces = [p.strip(" :;") for p in re.split(r"[,|;/]", body) if p.strip(" :;")]
    def phone_like(piece):
        return PHONE_ONLY.fullmatch(piece) or re.fullmatch(r"[+0(][0-9OIlSB\s()+.\-]{6,}", piece)
    if not labeled and not all(phone_like(p) for p in pieces):
        return []
    result = []
    lead = None  # the last complete number of this line
    for piece in pieces:
        digits = re.sub(r"\D", "", piece)
        if len(digits) < (5 if labeled else 7):
            continue  # Postcodes and decorative/icon text are not telephone evidence.
        normalized = re.sub(r"\bex\s+(?=\d)", "ext. ", piece, flags=re.I)
        # Some Indonesian cards print the country and area as "(62-21)". Only
        # this explicit notation supplies +62; a bare subscriber number never does.
        if region == "ID":
            normalized = re.sub(r"^\(\s*62\s*[- ]\s*([1-9]\d{1,2})\s*\)", r"+62\1", normalized)
        issues = []
        value = piece
        number = None
        if not PHONE_ONLY.fullmatch(normalized):
            issues.append("unparsed_phone_requires_review")
        elif region == "ID" and not normalized.lstrip().startswith("+") and not digits.startswith("0"):
            # ID has valid variable-length prefixes that can silently absorb a foreign number.
            issues.append("phone_country_or_area_code_required")
        else:
            try:
                parsed_number = phonenumbers.parse(normalized, region)
                if not phonenumbers.is_valid_number(parsed_number):
                    issues.append("phone_number_requires_review")
                else:
                    number = lead = parsed_number
                    value = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
                    if number.extension:
                        value += ";ext=" + number.extension
            except phonenumbers.NumberParseException:
                issues.append("unparsed_phone_requires_review")
        if (shared and lead is not None and digits == piece.replace(" ", "").replace("-", "").replace(".", "")
                and issues in (["phone_country_or_area_code_required"], ["phone_number_requires_review"])):
            completed = _shared_area_code(lead, digits)
            if completed:
                value, issues, number = completed, [], phonenumbers.parse(completed, None)
        result.append((value, issues, _phone_kind(printed, number)))
    return result


def _contacts(parsed, line, region, shared=True):
    found = False
    # Explicit value labels and addresses own their numbers: never extract a postcode as a phone.
    explicit_contact = (EMAIL_RE.search(line.text) or WEB_RE.search(line.text)
                        or BARE_WEB_RE.fullmatch(line.text))
    if (ADDRESS_RE.search(line.text) and not explicit_contact) or LABELED.match(line.text):
        return False
    # A label or groups of digits may occupy separate OCR boxes on one printed row.
    # Keep the row's original boxes as evidence while parsing the complete number.
    # Two complete phone boxes stay separate. Joining is for a label/number or
    # fragments of one number, not two printed contacts whose boxes happen to touch.
    separate_numbers = len(line.spans) > 1 and all(_phones(_without_icon(span.text), region)
                                                   for span in line.spans)
    phones = [] if separate_numbers else _phones(line.text, region, shared)
    if phones:
        for index, (value, issues, kind) in enumerate(phones):
            parsed.add("phones", value, line.spans, issues, assignment="pattern", contact_index=index, kind=kind)
        return True
    for span in line.spans:
        text = _without_icon(span.text).strip(EDGE_MARKS)
        social = SOCIAL_RE.fullmatch(text)
        if social and "." not in social[1]:
            parsed.add("social_handles", social[1], [span], assignment="pattern")
            found = True
            continue
        email_matches = list(EMAIL_RE.finditer(text))
        for index, match in enumerate(email_matches):
            value = match.group().rstrip(".,;")
            try:
                value = validate_email(value, check_deliverability=False).normalized
                issues = []
            except EmailNotValidError:
                issues = ["invalid_email_syntax"]
            parsed.add("emails", value, [span], issues, assignment="pattern", contact_index=index)
            found = True
        if "@" in text and not email_matches:
            if social:
                parsed.add("social_handles", social[1], [span], assignment="pattern")
            else:
                parsed.add("emails", text, [span], ["unparsed_email_requires_review"], assignment="pattern")
            found = True
            continue
        masked = EMAIL_RE.sub(lambda m: " " * len(m.group()), text)
        web_matches = list(WEB_RE.finditer(masked))
        bare = not web_matches
        if not web_matches:
            bare_text = re.sub(r"^(?:web(?:site)?|situs|url|w)\s*[:.]\s*", "", masked, flags=re.I).strip()
            # A dot inside a name, qualification or sentence is not a website anchor.
            bare_match = BARE_WEB_RE.fullmatch(bare_text)
            web_matches = [bare_match] if bare_match else []
        for index, match in enumerate(web_matches):
            normalized, issues = _website(match.group())
            if bare and not re.match(r"^(?:web(?:site)?|situs|url|w)\s*[:.]", masked, re.I):
                issues.append("bare_domain_requires_review")
            parsed.add("websites", normalized, [span], issues, assignment="pattern", contact_index=index)
            found = True
        if not email_matches and not web_matches:
            for index, (value, issues, kind) in enumerate(_phones(text, region, shared)):
                parsed.add("phones", value, [span], issues, assignment="pattern", contact_index=index, kind=kind)
                found = True
    return found


def _near_below(upper, lower, max_gap=1.8):
    gap = lower.y - (upper.y + upper.height)
    align = (abs(upper.x - lower.x) <= 2 * max(upper.height, lower.height)
             or abs(upper.right - lower.right) <= max(upper.height, lower.height)
             or abs(upper.center - lower.center) <= max(upper.height, lower.height))
    return -0.6 * min(upper.height, lower.height) <= gap <= max_gap * max(upper.height, lower.height) and align


def _person(text, fragment=False):
    words = text.split()
    return ((1 if fragment else 2) <= len(words) <= 6 and len(text) >= 2
            and all(c.isalpha() or c in " .,'-’&" for c in text)
            # "Z O H O" is a letterspaced logo, not initials.
            and any(len(word.strip(".,")) > 1 for word in words)
            and not PLACEHOLDER_RE.fullmatch(text)
            and not SERVICE_RE.search(text) and not LOCALITY_RE.search(text)
            and not OFFICE_RE.fullmatch(text) and not AFFILIATION_RE.search(text)
            and not TITLE_MODIFIER_RE.fullmatch(text))


def _same_print(upper, lower):
    return min(upper.height, lower.height) >= .65 * max(upper.height, lower.height)


def _join_titles(lines):
    """Join a wrapped role only when the upper row is a recognizable title fragment."""
    used, replacements = set(), {}
    for index, line in enumerate(lines):
        if (index in used or not _role(line.text) or OFFICE_RE.fullmatch(line.text)
                or COMPANY_RE.search(line.text) or ADDRESS_RE.search(line.text)):
            continue
        parts = [(index, line)]
        for _ in range(2):
            first = parts[0][1]
            choices = [(i, other) for i, other in enumerate(lines[:parts[0][0]]) if i not in used
                       and _near_below(other, first, max_gap=.6) and _same_print(other, first)]
            if not choices:
                break
            i, upper = max(choices, key=lambda item: item[1].y)
            # A complete independent title must not absorb another person's title.
            modifier = TITLE_MODIFIER_RE.fullmatch(upper.text) or (
                JOB_RE.search(upper.text) and not re.search(
                    r"\b(?:manager|director|executive|officer|consultant|direktur|kepala)\b", upper.text, re.I))
            if not modifier or OFFICE_RE.fullmatch(upper.text) or SERVICE_RE.search(upper.text):
                break
            parts.insert(0, (i, upper))
        if len(parts) > 1:
            used.update(i for i, _ in parts)
            replacements[parts[0][0]] = Line(" ".join(part.text for _, part in parts),
                                             [span for _, part in parts for span in part.spans])
    return [replacements[i] if i in replacements else line for i, line in enumerate(lines)
            if i not in used or i in replacements]


def _name_pairs(lines, assigned, jobs):
    """Use the nearest name row above each title; a tightly wrapped row can precede it."""
    paired = []
    for job in jobs:
        choices = [(i, line) for i, line in enumerate(lines) if i not in assigned
                   and _person(line.text, fragment=True) and _near_below(line, job)]
        if not choices:
            continue
        index, bottom = max(choices, key=lambda item: item[1].y)
        parts = [(index, bottom)]
        upper = [(i, line) for i, line in enumerate(lines[:index]) if i not in assigned
                 and _person(line.text, fragment=True) and _same_print(line, bottom)
                 and _near_below(line, bottom, max_gap=.45)]
        if upper:
            parts.insert(0, max(upper, key=lambda item: item[1].y))
        text = " ".join(line.text for _, line in parts)
        if _person(text, fragment=True):
            paired.append(([i for i, _ in parts], Line(text, [s for _, line in parts for s in line.spans])))
    return paired


# "JI." and "J1." are this recogniser reading the lowercase l of "Jl." as I or 1 — the
# same glyph. The Indonesian street abbreviation is fixed ("Jalan"), so the prefix is
# written out instead of being kept uncertain forever. Only the two ambiguous characters
# change; the rest of the line, the spacing and the raw reading in the evidence boxes are
# untouched. A prefix that is guesswork rather than a known glyph confusion stays flagged.
#
# A card often prints the street after the building, and without the full stop: "Unit A,
# Jl Melati No 69". At the start of such a part of the line the same reading is settled
# the same way. Anywhere else "JI Expo" may be a name, so the line is held for review
# instead; a block or unit code ("Blok J1 No. 5") is neither.
STREET_NAME = r"(?=\.?\s+(?!(?:No|Kav|Blok|RT|RW|Lt|Unit)\b)[A-Z][A-Za-z]{2})"
STREET_PART_RE = re.compile(r"(?:^|(?<=[,;/–-]\s)|(?<=[,;/–-]))J[I1]" + STREET_NAME)
STREET_UNSETTLED_RE = re.compile(r"(?<![\w.])J[I1]" + STREET_NAME)
UNIT_BEFORE_RE = re.compile(
    r"\b(?:blok|block|kav|kavling|unit|no|nomor|lt|lantai|tower|cluster|tipe|type)\.?\s*$", re.I)
# "Melati II" read with a lowercase l is not a word: it is a numeral or a block code, and
# which one is not settled here.
NUMERAL_RE = re.compile(r"(?<![\w.])(?=[Il1]*l)[Il1]{2,4}(?![\w.])")


def _canonical_street(text: str) -> tuple[str, list[str]]:
    text, issues = canonical_street(text)
    text = STREET_PART_RE.sub(lambda found: "JL" if text[found.end():].lstrip(". ")[:8].isupper() else "Jl", text)
    if any(not UNIT_BEFORE_RE.search(text[:found.start()]) for found in STREET_UNSETTLED_RE.finditer(text)):
        issues = issues + ["uncertain_street_prefix"]
    if NUMERAL_RE.search(text):
        issues = issues + ["ambiguous_numeral_requires_review"]
    return text, issues


def _fold(text: str) -> str:
    return text.lower().translate(LOOKALIKE_FOLD)


def _as_spelled(word: str, spelling: str) -> str:
    """``word`` with each lookalike letter replaced by the one the mailbox spells there."""
    capitals = all(c.isupper() for c in word if c.isalpha() and c not in "Il")
    letters = iter(spelling)
    result = []
    for position, character in enumerate(word):
        wanted = next(letters) if character.isalpha() else character
        if character.lower() == wanted:
            result.append(character)
        else:
            result.append(wanted.upper() if capitals or position == 0 else wanted)
    return "".join(result)


def _spelled_by_mailbox(words: list[str], local: str) -> tuple[list[str], set[int], int] | None:
    """Match a printed name line against the mailbox of a printed email address.

    "b.irawan" carries "Budi Irawan": every part of the mailbox is one of the words or
    the initial of one, and at least one word is spelled out. Returns the words with the
    letters the mailbox settles — it is printed in lowercase, where i and l differ, so
    "lrawan" is "Irawan" — the positions of the words it spells out in full, and how many
    words it touches. None when the mailbox is a shared one ("info", "sales") or belongs
    to another name.
    """
    parts = [re.sub(r"\d+", "", part) for part in re.split(r"[._+-]+", local.lower())]
    parts = [part for part in parts if part]
    if not parts or any(part in SHARED_MAILBOX for part in parts) or not all(part.isalpha() for part in parts):
        return None
    target = "".join(parts)
    names = [(index, "".join(c for c in word if c.isalpha())) for index, word in enumerate(words)]
    names = [(index, letters) for index, letters in names if letters]

    def search(position: int, used: frozenset, spelled: bool):
        if position == len(target):
            return [] if spelled else None
        for index, letters in names:
            end = position + len(letters)
            if index not in used and len(letters) >= 2 and _fold(target[position:end]) == _fold(letters):
                rest = search(end, used | {index}, spelled or len(letters) >= 3)
                if rest is not None:
                    return [(index, position, end)] + rest
        for index, letters in names:
            if index not in used and _fold(target[position]) == _fold(letters[0]):
                rest = search(position + 1, used | {index}, spelled)
                if rest is not None:
                    return [(index, position, position)] + rest
        return None

    found = search(0, frozenset(), False)
    if found is None:
        return None
    settled = list(words)
    for index, start, end in found:
        if end > start:
            settled[index] = _as_spelled(words[index], target[start:end])
    return settled, {index for index, start, end in found if end > start}, len(found)


def _named_by_mailbox(line, mailboxes, words_needed=1):
    """The text of a name line as a printed mailbox spells it, and the boxes to score it
    by: a box the mailbox spells out completely is as certain as the mailbox.

    ``words_needed`` is how many words of the line the mailbox has to touch. One word is
    enough to confirm a line a title already marks as the name ("budi@" under "Budi
    Santoso"); alone it would also make a name of "Showroom Contoh" for "showroom@".
    """
    boxes = [_without_icon(span.text).strip(EDGE_MARKS).split() for span in line.spans]
    words = [word for box in boxes for word in box]
    if " ".join(words) != line.text:
        boxes, words = [line.text.split()], line.text.split()
    for local, observation in mailboxes:
        match = _spelled_by_mailbox(words, local)
        if match is None or match[2] < words_needed:
            continue
        settled, spelled, _ = match
        scored, first = [], 0
        for span, box in zip(line.spans, boxes, strict=False):
            named = [index for index in range(first, first + len(box)) if any(c.isalpha() for c in words[index])]
            sure = len(boxes) == len(line.spans) and bool(named) and all(index in spelled for index in named)
            certainty = observation.score
            scored.append(span.model_copy(update={"score": certainty, "content_score": certainty}) if sure else span)
            first += len(box)
        return " ".join(settled), (scored if len(scored) == len(line.spans) else None)
    return None


# A capitalised name does not start a word with a lowercase l before a consonant: that
# is a capital I ("lrawan", "lndra"). Without an email address to settle it, it is held.
UNCERTAIN_INITIAL_RE = re.compile(r"(?<!\S)l(?=[bcdfghjklmnpqrstvwxyz])")


def _name_doubts(text: str) -> list[str]:
    return ["uncertain_leading_character"] if UNCERTAIN_INITIAL_RE.search(text) and re.search(r"[A-Z]", text) else []


def _host_name(host: str) -> str | None:
    """What a company's own host is called: "contohmedia" for contohmedia.com, "contoh" for
    mail.contoh.net.id. None for a free mail host, which names nobody."""
    parts = [part for part in host.lower().split(".") if part and part != "www"][:-1]
    while len(parts) > 1 and parts[-1] in DOMAIN_CATEGORY:
        parts.pop()
    if not parts or len(parts[-1]) < 3 or parts[-1] in FREE_MAIL | DOMAIN_CATEGORY:
        return None
    return parts[-1]


def _site_names(parsed: Parsed, websites: bool = True) -> list[str]:
    """The names of the card's own mail hosts and, unless left out, of its websites."""
    hosts = [item.value.rsplit("@", 1)[1] for item in parsed.fields.get("emails", [])
             if not item.issues and "@" in item.value]
    if websites:
        hosts += [urlsplit(item.value).hostname or "" for item in parsed.fields.get("websites", [])
                  if not item.issues]
    names = []
    for host in hosts:
        name = _host_name(host)
        if name is not None and name not in names:
            names.append(name)
    return names


def _mailboxes(parsed: Parsed, personal: bool = False) -> list[tuple[str, Observation]]:
    """The mailbox of every cleanly read email address, with its observation.

    ``personal`` keeps only mailboxes at a company's own host that are not that host's
    name: "budi.santoso@contoh.co.id" is a person at a company. "contohmedia@gmail.com"
    may be the shop itself, and so may "contoh@contoh.co.id".
    """
    found = []
    for item in parsed.fields.get("emails", []):
        if item.issues or "@" not in item.value:
            continue
        local, host = item.value.rsplit("@", 1)
        name = _host_name(host)
        if personal and (name is None or re.sub(r"[^a-z0-9]", "", local.lower()) == re.sub(r"[^a-z0-9]", "", name)):
            continue
        found.append((local, item))
    return found


def _spelled_by_site(words: list[str], site: str) -> int:
    """How many leading words of a logotype a site name spells; 0 when it is another name."""
    wanted = re.sub(r"[^a-z0-9]", "", site)
    joined = ""
    for count, word in enumerate(words, 1):
        joined += re.sub(r"[^a-z0-9]", "", word.lower())
        if joined == wanted or any(joined + filler == wanted for filler in DOMAIN_FILLER):
            return count
        if not wanted.startswith(joined):
            break
    return 0


def _site_brand(leftovers, assigned, sites):
    """The tallest logotype that the card's own domain names, as (text, lines), or None."""
    found = _site_brands(leftovers, assigned, sites)
    return max(found, key=lambda item: item[2])[:2] if found else None


def _site_brands(leftovers, assigned, sites):
    """Every logotype or name line that the card's own domain names, as (text, lines,
    height, how many of its leading words the domain spells).

    A card without a "PT ..." line still names its company twice: in the logo and in the
    domain of its addresses. The logo is used as printed when the domain spells its first
    words ("SINAR JAYA ABADI" for sinarjaya.com), or all the words of a logo set
    in two sizes ("Samudra" over "MARINE" for samudramarine.id). A logo mark read as
    thin strokes in front of the name ("iicontohmedia" for contohmedia.com) is not part of it.
    """
    free = [(index, line) for index, line in leftovers if index not in assigned]

    def stacked(first, same_print):
        """Rows of one word each, printed directly under the first."""
        rows = [first]
        while len(rows) < 4:
            last = rows[-1][1]
            below = [(i, other) for i, other in free if i not in {j for j, _ in rows}
                     and _near_below(last, other, max_gap=.6) and len(other.text.split()) == 1
                     and other.text.isalpha() and not SERVICE_RE.search(other.text)
                     and (not same_print or (
                         other.text.isupper() == first[1].text.isupper()
                         and min(last.height, other.height) >= .8 * max(last.height, other.height)
                         and abs(last.x - other.x) <= .6 * last.height))]
            if not below:
                break
            rows.append(min(below, key=lambda item: item[1].y))
        return rows

    def words_of(rows):
        return [word for _, row in rows for word in row.text.split()]

    brands = []
    for first in free:
        line = first[1]
        if not (1 <= len(line.text.split()) <= 4 and all(c.isalpha() or c in " .&'-" for c in line.text)):
            continue
        logotype, loose = stacked(first, True), stacked(first, False)
        found = None
        for site in sites:
            spelled = _spelled_by_site(words_of(logotype), site)
            if spelled:
                found = (" ".join(row.text for _, row in logotype), logotype, spelled)
                break
            whole = next((loose[:size] for size in range(len(loose), 1, -1)
                          if _spelled_by_site(words_of(loose[:size]), site) == len(words_of(loose[:size]))), None)
            if whole:
                found = (" ".join(row.text for _, row in whole), whole, len(words_of(whole)))
                break
            word = line.text
            extra = len(word) - len(site)
            if " " not in word and 0 < extra <= 3:
                if word.lower().endswith(site) and set(word[:extra]) <= STROKES:
                    found = (word[extra:], [first], 1)
                    break
                if word.lower().startswith(site) and set(word[-extra:]) <= STROKES:
                    found = (word[:-extra], [first], 1)
                    break
        if found:
            text, rows, spelled = found
            brands.append((text, rows, line.height, spelled))
    return brands


def _closed_up(text: str) -> str:
    """A letterspaced word written closed up: "A B C" is ABC, the rest is left alone."""
    return re.sub(r"\b[^\W\d_](?: [^\W\d_]){2,}\b", lambda found: found.group().replace(" ", ""), text)


def _short_for(brand: str, legal: str) -> bool:
    """Whether a brand only repeats the legal name: "CONTOH" or "Contoh Indonesia" beside
    "PT Contoh Lentera Abadi" is that company's short name, not a second one."""
    def letters(text):
        return re.sub(r"[^a-z0-9]", "", text.lower()).translate(LOOKALIKE_FOLD)

    own = [word for word in brand.split() if re.sub(r"[^a-z0-9]", "", word.lower()) not in DOMAIN_FILLER]
    held = {letters(word) for word in legal.split()}
    return letters(brand) in letters(legal) or (bool(own) and all(letters(word) in held for word in own))


def parse(spans: list[Span], region: str = "ID", shared_area_code: bool = True) -> Parsed:
    parsed = Parsed()
    lines = _join_titles(_lines(normalized(spans)))
    assigned = set()
    companies, jobs, addresses, leftovers = [], [], [], []
    office_followers = set()
    for index, heading in enumerate(lines):
        if OFFICE_RE.fullmatch(heading.text):
            assigned.add(index)
            following = [(i, line) for i, line in enumerate(lines[index + 1:], index + 1)
                         if _near_below(heading, line, max_gap=.85)]
            if following:
                i, first = min(following, key=lambda item: item[1].y)
                if (not contact_text(first.text) and not COMPANY_RE.search(first.text)
                        and not JOB_RE.search(first.text) and any(
                            _near_below(first, other, max_gap=.85) and ADDRESS_RE.search(other.text)
                            for other in lines[i + 1:])):
                    office_followers.add(i)
        # Some estates print just a building/complex name and unit numbers, then
        # the city and postcode. Require both rows before treating it as an address.
        elif (re.search(r"\d", heading.text) and len(re.findall(r"[^\W\d_]{2,}", heading.text)) >= 2
              and not COMPANY_RE.search(heading.text) and not JOB_RE.search(heading.text)
              and not any(mark in heading.text for mark in ("@", "http", "www."))
              and not PHONE_LABEL.match(heading.text)):
            if any(_near_below(heading, other, max_gap=.85) and LOCALITY_RE.search(other.text)
                   and re.search(r"\b\d{5}\b", other.text) for other in lines[index + 1:]):
                office_followers.add(index)
    for index, line in enumerate(lines):
        if not line.text or index in assigned:
            continue
        if AFFILIATION_RE.search(line.text):
            assigned.add(index)
            continue
        # A compact address sometimes ends in "Tel: +62 ..." in the same OCR box.
        # Both observations retain that box; the phone text is not part of the address.
        inline = INLINE_PHONE_LABEL.search(line.text)
        if inline and inline.start() and (ADDRESS_RE.search(line.text[:inline.start()])
                                          or LOCALITY_RE.search(line.text[:inline.start()])
                                          or re.search(r"\b\d{5}\b", line.text[:inline.start()])):
            if _contacts(parsed, Line(line.text[inline.start():], line.spans), region, shared_area_code):
                line = Line(line.text[:inline.start()].rstrip(" ,;|"), line.spans)
                lines[index] = line
        labeled = LABELED.match(line.text)
        if labeled:
            key = next(name for name in LABEL_WORDS if labeled.group(name))
            value = labeled.group("value")
            if key == "address":
                # A labelled address is the same printed line as a pattern-matched one;
                # the known Jl./JI. glyph confusion is settled the same way.
                value, issues = _canonical_street(value)
                parsed.add(key, value, line.spans, issues, assignment="label")
            else:
                parsed.add(key, value, line.spans, assignment="label")
            assigned.add(index)
            if key == "address":
                addresses.append((index, line, parsed.fields[key][-1]))
        elif _contacts(parsed, line, region, shared_area_code):
            assigned.add(index)
        elif (ADDRESS_RE.search(line.text) or index in office_followers) and not COMPANY_RE.search(line.text):
            text, issues = _canonical_street(line.text)
            parsed.add("address", text, line.spans, issues, assignment="pattern")
            addresses.append((index, line, parsed.fields["address"][-1]))
            assigned.add(index)
        elif COMPANY_RE.search(line.text):
            issues = ["template_placeholder_requires_review"] if PLACEHOLDER_RE.fullmatch(line.text) else []
            parsed.add("company", line.text, line.spans, issues, assignment="pattern")
            companies.append((index, line, parsed.fields["company"][-1]))
            assigned.add(index)
        elif _role(line.text):
            # A decorative leading bar can be recognized as I. Keep it under review, never silently erase it.
            issues = ["uncertain_leading_character"] if re.match(r"^[I|]\s+", line.text) else []
            parsed.add("job_title", line.text, line.spans, issues, assignment="pattern")
            jobs.append(line)
            assigned.add(index)
        else:
            leftovers.append((index, line))

    # A printed country suffix on the next row belongs to the same legal name.
    # Do not extend it with arbitrary logo text or reconstruct it from a domain.
    for start, company, observation in companies:
        for index, candidate in enumerate(lines[start + 1:], start + 1):
            if (index not in assigned and _near_below(company, candidate, max_gap=.45)
                    and candidate.text == "INDONESIA"):
                observation.value += " " + candidate.text
                observation.spans.extend(candidate.spans)
                assigned.add(index)
                break

    # Consecutive floor/street lines are one address, not conflicting addresses.
    address_at = {index: observation for index, _, observation in addresses}
    merged = set()
    for start, line, observation in addresses:
        if start in merged:
            continue
        previous = line
        row_count = 1
        for index, candidate in enumerate(lines[start + 1:], start + 1):
            if candidate.y > previous.y + 3 * previous.height:
                break
            if not _near_below(previous, candidate, max_gap=0.85):
                continue
            if ((index in assigned and index not in address_at)
                    or JOB_RE.search(candidate.text) or COMPANY_RE.search(candidate.text)):
                break
            if index in address_at and address_at[index].assignment == "label":
                break  # another explicit address starts a new block
            if len(candidate.text) < 6 or not (index in address_at or LOCALITY_RE.search(candidate.text)
                                              or "," in candidate.text or re.search(r"\d", candidate.text)):
                break
            value, issues = _canonical_street(candidate.text)
            observation.value += " " + value
            observation.issues.extend(issues)
            observation.spans.extend(candidate.spans)
            if index in address_at:
                parsed.fields["address"].remove(address_at[index])
                merged.add(index)
            assigned.add(index)
            previous = candidate
            row_count += 1
            if row_count >= 7:
                break

    people = [(i, line) for i, line in leftovers if i not in assigned and _person(line.text)]
    paired = _name_pairs(lines, assigned, jobs)
    person = None
    if "full_name" not in parsed.fields:
        # A printed mailbox that spells a line of the card says that line is a name: a
        # person's at a company's own host, perhaps the shop's own at a free one. The
        # value is always the printed line; nothing is taken from the address that the
        # card does not print as a name.
        def spelled_out(skip, mailboxes, words_needed=2):
            return [(i, line, named) for i, line in leftovers if i not in assigned and i not in skip
                    and _person(line.text, fragment=True)
                    and (named := _named_by_mailbox(line, mailboxes, words_needed)) is not None]

        if len(paired) == 1:
            indexes, person = paired[0]
            named = _named_by_mailbox(person, _mailboxes(parsed))
            others = [] if named else spelled_out(indexes, _mailboxes(parsed, personal=True))
            if others:
                # The title stands under one line and a personal mailbox spells another.
                for line in [person] + [line for _, line, _ in others]:
                    parsed.add("full_name", line.text, line.spans, ["multiple_person_blocks"], assignment="layout")
                assigned.update(i for i, _, _ in others)
                person = None
            else:
                text, scored = named or (person.text, None)
                parsed.add("full_name", text, person.spans, _name_doubts(text), value_spans=scored,
                           assignment="layout")
            assigned.update(indexes)
        elif paired:
            for indexes, line in paired:
                parsed.add("full_name", line.text, line.spans, ["multiple_person_blocks"], assignment="layout")
                assigned.update(indexes)
        else:
            named = spelled_out((), _mailboxes(parsed, personal=True))
            unsure = [] if named else spelled_out((), _mailboxes(parsed), words_needed=1)
            if len(named) == 1:
                index, person, (text, scored) = named[0]
                parsed.add("full_name", text, person.spans, _name_doubts(text), value_spans=scored,
                           assignment="contact")
                assigned.add(index)
            elif named:
                for index, line, _ in named:
                    parsed.add("full_name", line.text, line.spans, ["multiple_person_blocks"], assignment="contact")
                    assigned.add(index)
            elif len(unsure) == 1:
                # Spelled by a mailbox at a free mail host: a person or a shop. One candidate.
                _, line, (text, _) = unsure[0]
                parsed.add("full_name", text, line.spans, ["unlabeled_name_requires_review"],
                           assignment="heuristic")
            else:
                # Rank by observed typography, not alphabetic order or a dictionary of names.
                for index, line in sorted(people, key=lambda item: item[1].height, reverse=True)[:3]:
                    parsed.add("full_name", line.text, line.spans, ["unlabeled_name_requires_review"],
                               assignment="heuristic")

    # The card's own mail host settles a domain printed without "www.".
    hosts = _site_names(parsed, websites=False)
    for item in parsed.fields.get("websites", []):
        if item.issues == ["bare_domain_requires_review"] and _plain_site(item.value) in hosts:
            item.issues = []

    # The name a company trades under, printed beside a different legal name: "CONTOH
    # INDONESIA" over "PT. LENTERA GROUP", with addresses at contoh.co.id. The card's own
    # domain has to spell all of it, apart from what a company adds to its name ("Indonesia",
    # "Group"): a partner's logo or a tagline is not spelled by it, and "CONTOH Customer
    # Care" is a department. A line that is still a candidate for the person's name is
    # left to that. The fullest form is reported: the written name before the logo.
    legal = [item.value for item in parsed.fields.get("company", []) if item.assignment in ("pattern", "label")]
    if legal:
        offered = {id(span) for item in parsed.fields.get("full_name", []) for span in item.spans}
        names = []
        for text, block, height, spelled in _site_brands(leftovers, assigned, _site_names(parsed)):
            name, spans = _closed_up(text), [span for _, row in block for span in row.spans]
            if (all(word.lower().strip(".'-") in DOMAIN_FILLER for word in text.split()[spelled:])
                    and not any(_short_for(name, company) for company in legal)
                    and not any(id(span) in offered for span in spans)):
                names.append((len(re.sub(r"[^a-z0-9]", "", name.lower())), height, name, block, spans))
        if names:
            _, _, name, block, spans = max(names, key=lambda item: item[:2])
            parsed.add("company_alias", name, spans, assignment="contact")
            assigned.update(index for index, _ in block)

    if "company" not in parsed.fields:
        sites = _site_names(parsed)
        brand = _site_brand(leftovers, assigned, sites) if sites else None
        if brand is not None:
            text, block = brand
            parsed.add("company", text, [span for _, row in block for span in row.spans], assignment="contact")
            assigned.update(index for index, _ in block)

    # A separate brand can be proposed when a clear name/title pair already exists.
    # Without a business suffix, an explicit label or the card's own domain its role
    # remains uncertain.
    if "company" not in parsed.fields and person is not None:
        brands = [(i, line) for i, line in leftovers if i not in assigned and 1 <= len(line.text.split()) <= 4
                  and len(line.text) >= 3 and all(c.isalpha() or c in " .&'-" for c in line.text)
                  and not SERVICE_RE.search(line.text) and not PLACEHOLDER_RE.fullmatch(line.text)
                  and not JOB_RE.search(line.text)
                  and (line.y + line.height < person.y or line.right < person.x - person.height)]
        if brands:
            index, brand = max(brands, key=lambda item: item[1].height)
            value, evidence = brand.text, list(brand.spans)
            for other_index, other in leftovers:
                if other_index == index or other_index in assigned:
                    continue
                if (_near_below(brand, other, max_gap=0.5) and other.right < person.x - person.height
                        and 1 <= len(other.text.split()) <= 3 and other.text.isupper()
                        and all(c.isalpha() or c in " &" for c in other.text)):
                    value += " " + other.text
                    evidence.extend(other.spans)
                    break
            parsed.add("company", value, evidence, ["unlabeled_company_requires_review"],
                       assignment="heuristic")

    parsed.anchors = sum(bool(parsed.fields.get(k)) for k in LIST_FIELDS if k != "social_handles")
    return parsed


# Two readings of one line rarely differ by more than a character or two; a different
# value is a different string entirely.
NEAR_DUPLICATE_RATIO = 0.9


def _near_duplicate(first: str, second: str) -> bool:
    return SequenceMatcher(None, first, second).ratio() >= NEAR_DUPLICATE_RATIO


def resolve_field(observations: list[Observation], threshold: float, consensus: bool,
                  spacing_insensitive: bool = False) -> FieldResult:
    """Exact text agreement: punctuation in an email, phone, address or name is meaningful.

    With ``spacing_insensitive`` two readings that differ only in word breaks agree —
    "No.12" and "No. 12" are the same printed line — and the reading that kept the most
    breaks is reported, since this recogniser drops spaces far more often than it adds
    them. Characters and punctuation still have to match exactly.
    """
    if not observations:
        return FieldResult(reasons=["not_found"])
    grouped = {}
    for observation in observations:
        key = re.sub(r"\s+", "", observation.value) if spacing_insensitive else observation.value
        grouped.setdefault(key, []).append(observation)
    ranked = []
    for group in grouped.values():
        value = max(group, key=lambda o: (len(o.value.split()), o.score)).value
        reliable = {}
        evidence = {}
        for item in group:
            for span in item.spans:
                evidence[(span.pass_id, span.text, str(span.box))] = Evidence(**span.model_dump())
            if item.score >= threshold and not item.issues:
                for pass_id in {s.pass_id for s in item.value_spans or item.spans}:
                    if pass_id not in reliable or reliable[pass_id].score < item.score:
                        reliable[pass_id] = item
        support = sorted(reliable, key=lambda p: reliable[p].score, reverse=True)
        confirmed = len(support) >= (2 if consensus else 1)
        selected = [reliable[p] for p in support[:2]] if confirmed else group
        candidate = Candidate(value=value, ocr_score=round(min(x.score for x in selected), 4),
                              issues=sorted({i for x in selected for i in x.issues}),
                              evidence=list(evidence.values()), supporting_passes=support[:2] if confirmed else
                              sorted({s.pass_id for item in group for s in item.value_spans or item.spans}),
                              assignment=selected[0].assignment)
        ranked.append((candidate, confirmed, bool(reliable), len(support)))
    ranked.sort(key=lambda item: (item[1], item[2], item[3], item[0].ocr_score), reverse=True)
    best, confirmed, _, support_count = ranked[0]
    reasons = best.issues.copy()
    # A rival is dismissed only when it is outvoted AND is the same printed line read
    # slightly differently: three passes reading "Bogor" are not overruled by one reading
    # "Bogoc". A rival holding a genuinely different value still conflicts however few
    # passes back it, because that is a disagreement about what the card says.
    rivals = [
        item
        for item in ranked[1:]
        if item[2]
        and (item[3] >= max(support_count, 1) or not _near_duplicate(best.value, item[0].value))
    ]
    if rivals or (not confirmed and len(ranked) > 1):
        reasons.append("conflicting_readings")
    if best.ocr_score < threshold:
        reasons.append("low_ocr_score")
    if consensus and len(best.supporting_passes) < 2:
        reasons.append("second_read_required")
    return FieldResult(value=best.value if not reasons else None, candidate=best.value,
                       status="accepted" if not reasons else "review", ocr_score=best.ocr_score,
                       reasons=sorted(set(reasons)), candidates=[x[0] for x in ranked], assignment=best.assignment)


def _input_box(item, transforms):
    spans = item.value_spans or item.spans
    points = []
    for span in spans:
        matrix = np.asarray(transforms.get(span.pass_id, np.eye(3)))
        xy = np.asarray(span.box)
        mapped = np.c_[xy, np.ones(len(xy))] @ matrix.T
        points.extend((mapped[:, :2] / mapped[:, 2:]).tolist())
    points = np.asarray(points)
    return (*points.min(axis=0), *points.max(axis=0))


def resolve_contacts(observations, threshold, consensus, transforms):
    """Compare alternate reads of the same contact without merging separate numbers."""
    groups = []
    for item in observations:
        box = _input_box(item, transforms)
        match = None
        for group in groups:
            same = any(other.value == item.value for other in group)
            other = group[0]
            x0, y0, x1, y1 = _input_box(other, transforms)
            overlap = max(0, min(x1, box[2]) - max(x0, box[0])) * max(0, min(y1, box[3]) - max(y0, box[1]))
            area = max(1, min((x1 - x0) * (y1 - y0), (box[2] - box[0]) * (box[3] - box[1])))
            different_pass = not ({s.pass_id for s in item.spans} & {s.pass_id for s in other.spans})
            if same or (different_pass and item.contact_index == other.contact_index and overlap / area > 0.6):
                match = group
                break
        if match is None:
            groups.append([item])
        else:
            match.append(item)
    results = []
    for group in groups:
        result = resolve_field(group, threshold, consensus)
        # The kind the reads of the chosen number agree on. A fax label read by one pass
        # and missed by the other still makes it a fax line: only a label can say so.
        kinds = Counter(item.kind for item in group if item.kind and item.value == result.candidate)
        if kinds:
            result.phone_type = max(kinds, key=lambda kind: (kinds[kind], kind == "fax"))
        results.append(result)
    return results
