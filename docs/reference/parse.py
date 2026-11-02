import csv, re
from collections import defaultdict, OrderedDict
from openpyxl import load_workbook

DN125={'3.2':3,'4.3':4,'5.3':5,'6.4':6,'8.4':8,'10.5':10,'13':12,'17':16,'21':20,'25':24}
def fastener(name):
    n=re.sub(r'\.sldprt$','',name,flags=re.I).strip()
    m=re.match(r'(DIN 912|ISO 4762) M(\d+(?:\.\d+)?) x (\d+)',n)
    if m: return dict(t='Cıvata',desc='İmbus cıvata (silindirik başlı)',std='DIN 912 / ISO 4762',size=f'M{m[2]}x{m[3]}',d=float(m[2]),l=float(m[3]),orig=n)
    m=re.match(r'DIN 7991 - M(\d+(?:\.\d+)?) x (\d+)',n)
    if m: return dict(t='Cıvata',desc='Havşa başlı imbus cıvata',std='DIN 7991',size=f'M{m[1]}x{m[2]}',d=float(m[1]),l=float(m[2]),orig=n)
    m=re.match(r'Hexagon Nut (ISO 4034|ISO 4032|DIN 6915) - M(\d+)',n)
    if m:
        desc={'ISO 4034':'Altıgen somun (C sınıfı)','ISO 4032':'Altıgen somun','DIN 6915':'Altıgen somun (HV, yüksek mukavemet)'}[m[1]]
        return dict(t='Somun',desc=desc,std=m[1],size=f'M{m[2]}',d=float(m[2]),l=None,orig=n)
    m=re.match(r'DIN EN ISO 8733-(\d+)x(\d+)',n)
    if m: return dict(t='Pim',desc='Silindirik pim, iç dişli (ISO 8733)',std='DIN EN ISO 8733',size=f'Ø{m[1]}x{m[2]}',d=float(m[1]),l=float(m[2]),orig=n)
    m=re.match(r'DIN EN ISO 8750-(\d+)x(\d+)',n)
    if m: return dict(t='Pim',desc='Spiral yaylı pim',std='DIN EN ISO 8750',size=f'Ø{m[1]}x{m[2]}',d=float(m[1]),l=float(m[2]),orig=n)
    m=re.match(r'DIN EN 28734 - (\d+) x (\d+)',n)
    if m: return dict(t='Pim',desc='Silindirik pim (sertleştirilmiş, A tipi)',std='DIN EN 28734 (ISO 8734)',size=f'Ø{m[1]}x{m[2]}',d=float(m[1]),l=float(m[2]),orig=n)
    m=re.match(r'DIN 94-(\d+(?:\.\d+)?)x(\d+)',n)
    if m: return dict(t='Pim',desc='Kopilya',std='DIN 94',size=f'{m[1]}x{m[2]}',d=float(m[1]),l=float(m[2]),orig=n)
    m=re.match(r'Washer DIN 125 - (A|B) (\d+(?:\.\d+)?)',n)
    if m:
        bolt=DN125.get(m[2])
        return dict(t='Rondela',desc='Düz rondela'+(' (pahlı, B tipi)' if m[1]=='B' else ''),std='DIN 125-'+m[1]+(' / ISO 7089' if m[1]=='A' else ''),size=f'Ø{m[2]} (M{bolt})',d=float(bolt),l=None,orig=n)
    m=re.match(r'Washer ISO 7089 - (\d+)',n)
    if m:
        inner={3:'3.2',4:'4.3',5:'5.3',6:'6.4',8:'8.4',10:'10.5',12:'13',16:'17',20:'21'}[int(m[1])]
        return dict(t='Rondela',desc='Düz rondela',std='DIN 125-A / ISO 7089',size=f'Ø{inner} (M{m[1]})',d=float(m[1]),l=None,orig=n)
    m=re.match(r'Spring washer DIN 128 - A(\d+(?:\.\d+)?)',n)
    if m: return dict(t='Rondela',desc='Yaylı rondela',std='DIN 128',size=f'A{m[1]} (M{m[1]})',d=float(m[1]),l=None,orig=n)
    m=re.match(r'Parallel key A(\d+) x (\d+) x (\d+) DIN 6885',n)
    if m: return dict(t='Kama',desc='Paralel kama (A tipi)',std='DIN 6885',size=f'A{m[1]}x{m[2]}x{m[3]}',d=float(m[1]),l=float(m[3]),orig=n)
    m=re.match(r'Circlip DIN 471 - (\d+) x (\d+(?:\.\d+)?)',n)
    if m: return dict(t='Segman',desc='Dış segman (mil)',std='DIN 471',size=f'{m[1]}x{m[2]}',d=float(m[1]),l=None,orig=n)
    return None

def load_bom(p):
    rows=[]
    with open(p,encoding='utf-8-sig') as f:
        r=csv.reader(f,delimiter=';'); next(r)
        for x in r:
            if x and x[0].strip(): rows.append([c.strip() for c in x])
    out=[]; qty_at={}; name_at={}; hazir_at=set()
    for lvl,name,cnt,mat,w,rev,temin,kap in rows:
        depth=lvl.count('.')
        par=lvl.rsplit('.',1)[0] if depth else None
        mult=qty_at.get(par,1) if depth else 1
        q=int(cnt); tot=q*mult
        qty_at[lvl]=tot; base=re.sub(r'\.(sldprt|sldasm)$','',name,flags=re.I)
        name_at[lvl]=base
        in_hazir = par is not None and any(par==h or par.startswith(h+'.') for h in hazir_at)
        ext=name.rsplit('.',1)[-1].upper()
        if temin=='Hazır Alım' and ext=='SLDASM': hazir_at.add(lvl)
        top = name_at.get('.'.join(lvl.split('.')[:2])) if depth>=1 else base
        out.append(dict(lvl=lvl,depth=depth,name=name,pno=base,ext=ext,qty=q,mult=mult,tot=tot,
            mat='' if (not mat or 'not specified' in mat or 'belirli değil' in mat) else mat,
            w=float(w) if w else None,rev=rev,temin=temin,kap=kap,par=name_at.get(par,'') if par else '',
            top=top,in_hazir=in_hazir,fx=fastener(name)))
    return out

def load_t35(p):
    ws=load_workbook(p).active; out=OrderedDict()
    for row in ws.iter_rows(min_row=2):
        a,b,c,d,e,f,g=[x.value for x in row[:7]]
        if not b: continue
        fillc=row[1].fill.fgColor.rgb if row[1].fill and row[1].fill.fill_type=='solid' else None
        out[re.sub(r'\.SLDPRT$','',b,flags=re.I)]=dict(no=str(a),plus=str(a).endswith('+'),qty=int(c),mat=d,w=float(e),rev=f,txt=(g or '').strip(),fill=fillc)
    return out
