"""Tiny .docx writer (standard library only) matching the team's report layout:
bold title, justified 12pt body with **bold** phrases, and hyperlinked post titles."""

import re
import zipfile
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
HYPERLINK_REL = R_NS + "/hyperlink"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W_NS}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial" w:cs="Arial"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-IN"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="character" w:styleId="Hyperlink"><w:name w:val="Hyperlink"/>
<w:rPr><w:color w:val="1155CC"/><w:u w:val="single"/></w:rPr></w:style>
</w:styles>"""

BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.S)
BAD_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def _run(text, bold=False, size=24, color=None, italic=False, style=None):
    props = []
    if style:
        props.append(f'<w:rStyle w:val="{style}"/>')
    if bold:
        props.append("<w:b/><w:bCs/>")
    if italic:
        props.append("<w:i/><w:iCs/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    props.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
    return (f'<w:r><w:rPr>{"".join(props)}</w:rPr>'
            f'<w:t xml:space="preserve">{escape(BAD_XML_CHARS.sub("", text))}</w:t></w:r>')


def _rich_runs(text, size=24):
    """Turn 'plain **bold** plain' into runs."""
    runs, pos = [], 0
    for m in BOLD_RE.finditer(text):
        if m.start() > pos:
            runs.append(_run(text[pos:m.start()], size=size))
        runs.append(_run(m.group(1), bold=True, size=size))
        pos = m.end()
    if pos < len(text):
        runs.append(_run(text[pos:], size=size))
    return "".join(runs)


def _para(runs, before=240, after=240, line=360, jc="both"):
    return (f'<w:p><w:pPr><w:spacing w:before="{before}" w:after="{after}" w:line="{line}" '
            f'w:lineRule="auto"/><w:jc w:val="{jc}"/></w:pPr>{runs}</w:p>')


class Document:
    def __init__(self):
        self.body = []
        self.links = []

    def title(self, text):
        self.body.append(_para(_run(text, bold=True, size=32), before=280, after=120, line=276))

    def heading(self, text):
        self.body.append(_para(_run(text, bold=True, size=24), before=240, after=120))

    def paragraph(self, text, size=24):
        self.body.append(_para(_rich_runs(text, size)))

    def link(self, text, url, note=None):
        self.links.append(url)
        rid = f"rIdL{len(self.links)}"
        runs = f'<w:hyperlink r:id="{rid}" w:history="1">{_run(text, size=24, style="Hyperlink")}</w:hyperlink>'
        if note:
            runs += _run("  (" + note + ")", size=18, color="666666", italic=True)
        self.body.append(_para(runs, before=0, after=240, line=276, jc="left"))

    def small(self, text):
        self.body.append(_para(_run(text, size=18, color="666666", italic=True),
                               before=240, after=0, line=276, jc="left"))

    def save(self, path, title="Reddit Report"):
        doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               f'<w:document xmlns:w="{W_NS}" xmlns:r="{R_NS}"><w:body>{"".join(self.body)}'
               f'<w:sectPr><w:pgSz w:w="12240" w:h="15840"/>'
               f'<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
               f'w:header="720" w:footer="720" w:gutter="0"/></w:sectPr></w:body></w:document>')
        rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/'
                '2006/relationships/styles" Target="styles.xml"/>']
        for n, url in enumerate(self.links, 1):
            rels.append(f'<Relationship Id="rIdL{n}" Type="{HYPERLINK_REL}" '
                        f'Target="{escape(url, {chr(34): "&quot;"})}" TargetMode="External"/>')
        rels.append("</Relationships>")
        core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
                'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
                f'<dc:title>{escape(title)}</dc:title><dc:creator>Reddit Alerts</dc:creator>'
                '</cp:coreProperties>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", CONTENT_TYPES)
            z.writestr("_rels/.rels", ROOT_RELS)
            z.writestr("docProps/core.xml", core)
            z.writestr("word/document.xml", doc)
            z.writestr("word/styles.xml", STYLES)
            z.writestr("word/_rels/document.xml.rels", "".join(rels))
