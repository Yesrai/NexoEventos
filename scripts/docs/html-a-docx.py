import sys,zipfile,pathlib,re
from html.parser import HTMLParser
from xml.sax.saxutils import escape
from PIL import Image
base=pathlib.Path(sys.argv[1]).parent
html=pathlib.Path(sys.argv[1]).read_text()
body=html.split('<body>')[1].split('</body>')[0]
media=[];body_xml=[]
def run(t,b=False,i=False,c=False,link=False,sz=None):
    if not t: return ''
    pr=''
    if b: pr+='<w:b/>'
    if i: pr+='<w:i/>'
    if c: pr+='<w:rFonts w:ascii="Menlo" w:hAnsi="Menlo"/><w:shd w:val="clear" w:fill="F2F2F2"/>'
    if link: pr+='<w:color w:val="12355B"/><w:u w:val="single"/>'
    if sz: pr+=f'<w:sz w:val="{sz}"/>'
    return f'<w:r><w:rPr>{pr}</w:rPr><w:t xml:space="preserve">{escape(t)}</w:t></w:r>'
class P(HTMLParser):
    def __init__(s):
        super().__init__(convert_charrefs=True); s.runs=[];s.st={'b':0,'i':0,'c':0,'a':0};s.kind=None;s.tbl=None;s.cell=None;s.row=None;s.list=[];s.cellp=[]
    def flush(s,style=None,num=False):
        x=''.join(s.runs);s.runs=[]
        if not x: return None
        ppr=f'<w:pStyle w:val="{style}"/>' if style else ''
        if num: ppr+='<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'
        return f'<w:p><w:pPr>{ppr}</w:pPr>{x}</w:p>'
    def emit(s,x):
        if x is None: return
        if s.cell is not None: s.cell.append(x)
        else: body_xml.append(x)
    def handle_starttag(s,t,a):
        a=dict(a)
        if t in('strong','b'): s.st['b']+=1
        elif t in('em','i'): s.st['i']+=1
        elif t=='code': s.st['c']+=1
        elif t=='a': s.st['a']+=1
        elif t in('h1','h2','h3','h4','p','li'): s.kind=t; s.runs=s.runs if s.cell is not None else []
        elif t=='table': s.tbl=[]
        elif t=='tr': s.row=[]
        elif t in('td','th'): s.cell=[]; s.hdr=(t=='th')
        elif t=='br': s.runs.append('<w:r><w:br/></w:r>')
        elif t=='img':
            src=a['src'];f=(base/src)
            if f.exists() and f.suffix=='.png':
                im=Image.open(f);w,h=im.size;wi=min(6.3,w/150);k=wi/ (w/150)
                cx=int(wi*914400);cy=int(h/w*cx);n=len(media)+1;media.append(f)
                d=f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{n}" name="img{n}" descr="{escape(a.get("alt",""))}"/><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{n}" name="img{n}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="rIdImg{n}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r>'
                s.runs.append(d)
            else: s.runs.append(run('['+a.get('alt','imagen')+']'))
        elif t in('ul','ol'): s.list.append(t)
    def handle_endtag(s,t):
        if t in('strong','b'): s.st['b']-=1
        elif t in('em','i'): s.st['i']-=1
        elif t=='code': s.st['c']-=1
        elif t=='a': s.st['a']-=1
        elif t in('h1','h2','h3','h4'): s.emit(s.flush('Heading'+t[1]))
        elif t=='p':
            if s.cell is None: s.emit(s.flush())
            else: s.runs.append('<w:r><w:br/></w:r>')
        elif t=='li': s.emit(s.flush(num=True))
        elif t in('td','th'):
            if s.runs: s.cell.append(s.flush())
            c=s.cell; s.cell=None
            s.row.append((c or ['<w:p/>'],s.hdr))
        elif t=='tr': s.tbl.append(s.row)
        elif t=='table':
            nc=max(len(r) for r in s.tbl); w=int(9500/nc)
            x='<w:tbl><w:tblPr><w:tblW w:w="5000" w:type="pct"/><w:tblBorders>'+''.join(f'<w:{e} w:val="single" w:sz="4" w:color="999999"/>' for e in('top','left','bottom','right','insideH','insideV'))+'</w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>'+''.join(f'<w:gridCol w:w="{w}"/>' for _ in range(nc))+'</w:tblGrid>'
            for r in s.tbl:
                x+='<w:tr><w:trPr><w:cantSplit/></w:trPr>'
                for c,h in r:
                    shd='<w:shd w:val="clear" w:fill="DFE8F3"/>' if h else ''
                    x+=f'<w:tc><w:tcPr><w:tcW w:w="{w}" w:type="dxa"/>{shd}</w:tcPr>'+''.join(c)+'</w:tc>'
                x+='</w:tr>'
            body_xml.append(x+'</w:tbl><w:p/>'); s.tbl=None
        elif t in('ul','ol'): s.list.pop()
    def handle_data(s,d):
        if not d.strip() and not s.runs: return
        d=re.sub(r'\s+',' ',d)
        sz=17 if s.cell is not None else None
        s.runs.append(run(d,s.st['b']>0 or (s.cell is not None and s.hdr and False),s.st['i']>0,s.st['c']>0,s.st['a']>0,sz))
P().feed(body)
ns='xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"'
doc=f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {ns}><w:body>{"".join(body_xml)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="900" w:right="800" w:bottom="900" w:left="800" w:header="400" w:footer="400"/></w:sectPr></w:body></w:document>'
def hs(n,sz,col): return f'<w:style w:type="paragraph" w:styleId="Heading{n}"><w:name w:val="heading {n}"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="100"/><w:outlineLvl w:val="{n-1}"/></w:pPr><w:rPr><w:b/><w:color w:val="{col}"/><w:sz w:val="{sz}"/></w:rPr></w:style>'
styles=f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="21"/><w:lang w:val="es-PE"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="80"/></w:pPr></w:pPrDefault></w:docDefaults><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>{hs(1,40,"12355B")}{hs(2,30,"12355B")}{hs(3,24,"12355B")}{hs(4,22,"12355B")}</w:styles>'
numbering='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:pPr><w:ind w:left="500" w:hanging="250"/></w:pPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>'
rels='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rIdS" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rIdN" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'+''.join(f'<Relationship Id="rIdImg{i+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{i+1}.png"/>' for i in range(len(media)))+'</Relationships>'
ct='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Default Extension="png" ContentType="image/png"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/></Types>'
root='<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'
with zipfile.ZipFile(sys.argv[2],'w',zipfile.ZIP_DEFLATED) as z:
    z.writestr('[Content_Types].xml',ct);z.writestr('_rels/.rels',root);z.writestr('word/document.xml',doc);z.writestr('word/styles.xml',styles);z.writestr('word/numbering.xml',numbering);z.writestr('word/_rels/document.xml.rels',rels)
    for i,f in enumerate(media): z.write(f,f'word/media/{i+1}.png')
print('imagenes',len(media))
