import csv, sys, re
sys.path.insert(0,'/home/claude/src')
from parse import load_bom
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.formatting.rule import FormulaRule, DataBarRule
from openpyxl.utils import get_column_letter as L
from openpyxl.chart import PieChart, BarChart, Reference
from openpyxl.chart.series import DataPoint
from openpyxl.chart.label import DataLabelList

D='/home/claude/v3/'
BOMSRC=D+'bom_new.csv'; BOMFIX=D+'bom_new_fixed.csv'
OUT_T=D+'T01_0000_0000_Takip_Listesi.xlsx'; OUT_P=D+'T01_0000_0000_Parca_Takip.xlsx'

# --- TSDacikboy tek hazır alım kalemi olarak işlensin (kullanıcı kararı)
with open(BOMSRC,encoding='utf-8-sig') as f: lines=list(csv.reader(f,delimiter=';'))
for x in lines[1:]:
    if x and x[1].strip()=='TSDacikboy.SLDASM': x[6]='Hazır Alım'
with open(BOMFIX,'w',encoding='utf-8',newline='') as f: csv.writer(f,delimiter=';').writerows(lines)
bom=load_bom(BOMFIX)

# --- kullanıcının güncel durumları
def read_rows(path):
    p=load_workbook(path)['Parça Listesi']; out=[]
    for r in range(6,p.max_row+1):
        v=[p.cell(r,c).value for c in range(1,16)]
        if any(x not in (None,'') for x in v): v[1]=(v[1] or '').strip(); out.append(v)
    return out
PU=read_rows(D+'parca_user.xlsx'); TU=read_rows(D+'takip_user.xlsx')
RENAME={'T01_2000_0002-P':'T01_2000_0002'}     # kullanıcı: aynı parça
st_exact={}; st_pno={}
for src in (TU,PU):                              # PU sonra → en güncel olan kazanır
    for v in src:
        if v[2]=='Eksik': continue
        rec=dict(durum=v[12],t35=v[13],temin=v[9])
        st_exact[(v[1],v[4])]=rec; st_pno[v[1]]=rec
eksik={v[1].replace(' (EKSİK)',''):v for v in PU if v[2]=='Eksik'}
tb=load_workbook(D+'takip_user.xlsx')['Bağlantı Özeti']
fx_status={(tb.cell(r,3).value,tb.cell(r,4).value):tb.cell(r,7).value for r in range(6,tb.max_row+1) if tb.cell(r,1).value}
old_pnos={v[1] for v in TU}|{v[1] for v in PU}

# --- satırları hazırla
rows=[]
for x in bom:
    if x['fx']: continue
    pno=x['pno']; isasm=x['ext']=='SLDASM'
    par=x['par'] if x['depth']>1 else 'T01_0000_0000'
    look=RENAME.get(pno,pno)
    rec=st_exact.get((look,par)) or st_pno.get(look)
    temin=x['temin']
    if not temin and rec and rec['temin'] in ('İmalat','Hazır Alım'): temin=rec['temin']
    if x['in_hazir']: temin='Hazır montaj içinde'
    elif not temin and not isasm: temin='Belirtilmemiş'
    note=''; new = look not in old_pnos
    if rec and not x['in_hazir']:
        durum=rec['durum']; t35=rec['t35']
        if pno in RENAME:
            note=f"Önceki listede {look} (Hazır Alım – {durum}) – kullanıcıya göre aynı parça"
            if temin=='İmalat' and durum in ('Sipariş Teslim Edildi','Sipariş Verildi','Sipariş Verilmedi'):
                durum={'Sipariş Teslim Edildi':'Üretildi'}.get(durum,'Üretilmedi')
        # temin değiştiyse geçersiz kalan durumu düzelt
        if temin=='İmalat' and durum in ('Sipariş Verilmedi','Sipariş Verildi'): durum='Üretilmedi'
        if temin=='Hazır Alım' and not isasm and durum in ('Üretilmedi','Üretildi'): durum='Sipariş Verilmedi'
    else:
        t35=None
        if x['in_hazir']: durum=None
        elif isasm: durum='Sipariş Verilmedi' if temin=='Hazır Alım' else 'Montajlanmadı'
        elif temin=='Hazır Alım': durum='Sipariş Verilmedi'
        elif temin=='İmalat': durum='Üretilmedi'
        else: durum=None
    if new and not x['in_hazir']: note=(note+'; ' if note else '')+"Yeni BOM'da eklendi"
    if pno=='TSDacikboy': note=(note+'; ' if note else '')+'Tek hazır alım kalemi olarak alındı (içindeki 30 tedarikçi parçası listelenmedi)'
    rows.append(dict(lvl=x['lvl'],depth=x['depth'],pno=pno,typ='Montaj' if isasm else 'Parça',grp=x['top'] if x['depth']>1 else '(Ana montaj)',par=par,
                     qty=x['qty'],tot=x['tot'],mat=x['mat'] or ('' if isasm else 'Belirtilmemiş'),w=x['w'],temin=temin,kap=x['kap'] or '',rev=x['rev'] or '-',
                     durum=durum,t35=t35,note=note,new=new and not x['in_hazir'],in_hazir=x['in_hazir'],ek=False))
    if look in eksik and not any(r_['ek'] and r_['pno']==pno+' (EKSİK)' for r_ in rows):
        e=eksik[look]
        rows.append(dict(lvl=x['lvl']+'+',depth=x['depth'],pno=pno+' (EKSİK)',typ='Eksik',grp=rows[-1]['grp'],par=par,qty=None,tot=e[6],mat=rows[-1]['mat'],w=x['w'],
                         temin=temin,kap=x['kap'] or '',rev=x['rev'] or '-',durum=e[12],t35=e[13],note=e[14] or 'Eksik adet (kullanıcı bildirimi)',new=False,in_hazir=False,ek=True))
removed=sorted({v[1] for v in PU if v[2]!='Eksik'} - {RENAME.get(r_['pno'],r_['pno']) for r_ in rows} )

# ===================================================================== ortak stil
FONT='Arial'; NAVY='1F3864'
thin=Side(style='thin',color='BFBFBF'); B=Border(left=thin,right=thin,top=thin,bottom=thin)
HF=PatternFill('solid',fgColor=NAVY); HFont=Font(name=FONT,bold=True,color='FFFFFF',size=10)
def fill(c): return PatternFill('solid',fgColor=c)
def F(**k): return Font(name=FONT,**{'size':10,**k})
base=F()
ORD=['Sipariş Verilmedi','Sipariş Verildi','Sipariş Teslim Edildi']; PRD=['Üretilmedi','Üretildi']; ASM=['Montajlanmadı','Montajlandı']
COL={'Sipariş Verilmedi':('FFC7CE','9C0006'),'Sipariş Verildi':('FFEB9C','9C5700'),'Sipariş Teslim Edildi':('C6EFCE','006100'),
     'Üretilmedi':('F8CBAD','833C0B'),'Üretildi':('BDD7EE','1F4E79'),'Montajlanmadı':('E7E6E6','3A3838'),'Montajlandı':('D9C3E9','5B2C83')}
CH={'Üretildi':'2E75B6','Üretilmedi':'E97B54','Sipariş Verilmedi':'E06666','Sipariş Verildi':'F1C232','Sipariş Teslim Edildi':'6AA84F'}
tfill={'Cıvata':'DDEBF7','Somun':'FFF2CC','Pim':'E2EFDA','Rondela':'EDE2F6','Kama':'FCE4D6','Segman':'DEEAF1'}
tchart={'Cıvata':'2E75B6','Somun':'F1C232','Pim':'6AA84F','Rondela':'8E7CC3','Kama':'E69138','Segman':'76A5AF'}
EKF='E4DFEC'; NEWF='D9EAD3'
HR=5

def header(ws,cols,widths):
    for i,(h,w) in enumerate(zip(cols,widths),1):
        c=ws.cell(HR,i,h); c.fill=HF; c.font=HFont; c.border=B; c.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
        ws.column_dimensions[L(i)].width=w
    ws.row_dimensions[HR].height=30
def status_cf(ws,rng,first):
    for k,(bg,fg) in COL.items():
        ws.conditional_formatting.add(rng,FormulaRule(formula=[f'{first}="{k}"'],fill=fill(bg),font=Font(name=FONT,bold=True,color=fg)))
def landscape(s):
    s.page_setup.orientation='landscape'; s.page_setup.fitToWidth=1; s.page_setup.fitToHeight=0
    s.sheet_properties.pageSetUpPr.fitToPage=True; s.print_title_rows=f'{HR}:{HR}'

ILR=['Bekliyor','Devam ediyor','Tamamlandı']
def to_ilerleme(d):
    if d in ('Üretildi','Sipariş Teslim Edildi','Montajlandı'): return 'Tamamlandı'
    if d in ('Sipariş Verildi','Üretimde'): return 'Devam ediyor'
    if d in ('Üretilmedi','Sipariş Verilmedi','Montajlanmadı'): return 'Bekliyor'
    return None
def durum_formula(r):
    return (f'=IF(M{r}="","",IF(J{r}="Hazır Alım",IF(M{r}="Tamamlandı","Sipariş Teslim Edildi",IF(M{r}="Devam ediyor","Sipariş Verildi","Sipariş Verilmedi")),'
            f'IF(C{r}="Montaj",IF(M{r}="Tamamlandı","Montajlandı","Montajlanmadı"),IF(J{r}="İmalat",IF(M{r}="Tamamlandı","Üretildi","Üretilmedi"),"Temin seçilmedi"))))')

def write_parts(ws,rlist,with_note,parts_only):
    ttl='T01_0000_0000 – Parça Listesi'
    sub=("Montaj satırları çıkarıldı; sadece imal edilecek ve satın alınacak kalemler. " if parts_only else "")+"Sarı \"İlerleme\" sütunundan seçin; \"Durum\" Temin Şekli'ne göre otomatik oluşur. Yeşil parça no = yeni BOM kalemi; mor satır = eksik adet."
    ws['A1']=ttl; ws['A1'].font=Font(name=FONT,bold=True,size=14,color=NAVY)
    ws['A2']=sub; ws['A2'].font=Font(name=FONT,italic=True,size=9,color='595959')
    cols=['Seviye','Parça No','Tip','Ana Grup','Üst Montaj','Adet','Toplam Adet','Malzeme','Birim Ağırlık (g)','Temin Şekli','Kaplama','Rev','İlerleme (seç)','Durum (otomatik)','T-35 Notu']+(['Not'] if with_note else [])
    widths=[9,24 if parts_only else 30,11,16,16,6,8,22,11,15,14,5,15,21,44]+([50] if with_note else [])
    header(ws,cols,widths); nc=len(cols)
    ws.cell(HR,13).fill=fill('BF8F00'); ws.cell(HR,14).fill=fill('595959')
    dvI=DataValidation(type='list',formula1='"'+','.join(ILR)+'"',allow_blank=True); ws.add_data_validation(dvI)
    dvT=DataValidation(type='list',formula1='"İmalat,Hazır Alım,Belirtilmemiş"',allow_blank=True); ws.add_data_validation(dvT)
    r=HR+1
    for x in rlist:
        indent='' if parts_only else '   '*(x['depth']-1)
        typ=x['typ']
        if parts_only and typ=='Montaj': typ='Hazır Alım Montaj'
        ilr=None if x['in_hazir'] else to_ilerleme(x['durum'])
        if ilr is None and not x['in_hazir'] and x['temin'] in ('İmalat','Hazır Alım'): ilr='Bekliyor'
        vals=[x['lvl'],indent+x['pno'],typ,x['grp'],x['par'],x['qty'],x['tot'],x['mat'],x['w'],x['temin'],x['kap'],x['rev'],ilr,
              None if x['in_hazir'] else durum_formula(r),x['t35']]+([x['note'] or None] if with_note else [])
        for i,v in enumerate(vals,1):
            c=ws.cell(r,i,v); c.font=base; c.border=B; c.alignment=Alignment(vertical='center',wrap_text=(i>=15))
        ws.cell(r,1).number_format='@'; ws.cell(r,9).number_format='#,##0.00'
        for cc in (6,7,12,13): ws.cell(r,cc).alignment=Alignment(horizontal='center',vertical='center')
        if x['ek']:
            for i in range(1,nc+1): ws.cell(r,i).font=F(bold=True,color='5B2C83'); ws.cell(r,i).fill=fill(EKF)
            ws.cell(r,7).font=F(bold=True,color='0000FF')
        elif x['typ']=='Montaj':
            for i in range(1,nc+1):
                ws.cell(r,i).font=F(bold=True)
                ws.cell(r,i).fill=fill('FCE4D6' if parts_only else ('DDEBF7' if x['depth']==1 else 'EEF4FB'))
        if x['in_hazir']:
            for i in range(1,nc+1): ws.cell(r,i).font=F(color='808080',italic=True)
        if not x['ek']:
            if x['mat']=='Belirtilmemiş': ws.cell(r,8).font=F(italic=True,color='C00000')
            if x['temin']=='Belirtilmemiş': ws.cell(r,10).font=F(italic=True,color='C00000')
            if x['new']: ws.cell(r,2).fill=fill(NEWF); ws.cell(r,2).font=F(bold=True,color='274E13')
            if with_note and x['note']: ws.cell(r,16).font=F(color='C00000')
        if not x['in_hazir']:
            dvI.add(ws.cell(r,13).coordinate)
            ws.cell(r,13).fill=fill('FFF2CC'); ws.cell(r,13).font=F(bold=True,color='0000FF')
            if x['typ']!='Montaj' or x['temin']=='Hazır Alım': dvT.add(ws.cell(r,10).coordinate)
        r+=1
    last=r-1
    status_cf(ws,f'N{HR+1}:N{last}',f'N{HR+1}')
    ws.conditional_formatting.add(f'N{HR+1}:N{last}',FormulaRule(formula=[f'N{HR+1}="Temin seçilmedi"'],font=Font(name=FONT,italic=True,color='C00000')))
    ws.conditional_formatting.add(f'M{HR+1}:M{last}',FormulaRule(formula=[f'M{HR+1}="Tamamlandı"'],fill=fill('E2EFDA'),font=Font(name=FONT,bold=True,color='375623')))
    ws.conditional_formatting.add(f'M{HR+1}:M{last}',FormulaRule(formula=[f'M{HR+1}="Devam ediyor"'],fill=fill('FFEB9C'),font=Font(name=FONT,bold=True,color='7F6000')))
    ws.auto_filter.ref=f'A{HR}:{L(nc)}{last}'; ws.freeze_panes=f'C{HR+1}'
    ws['A3']='Filtrelenen satır:'; ws['A3'].font=F(bold=True); ws['C3']=f'=SUBTOTAL(103,B{HR+1}:B{last})'
    ws['E3']='Filtrelenen toplam adet:'; ws['E3'].font=F(bold=True); ws['G3']=f'=SUBTOTAL(109,G{HR+1}:G{last})'
    for a in ('C3','G3'): ws[a].font=F(bold=True,color=NAVY); ws[a].fill=fill('FFF2CC')
    ws['I3']='Renkler:'; ws['I3'].font=F(bold=True)
    leg=[('Yeni BOM kalemi',NEWF,'274E13'),('Eksik adet',EKF,'5B2C83')]+([('Hazır alım montaj','FCE4D6','000000')] if parts_only else [('Ana grup montaj','DDEBF7',NAVY)])
    for col,(t,bg,fg) in zip(('J','K','L'),leg):
        c=ws[f'{col}3']; c.value=t; c.fill=fill(bg); c.font=F(bold=True,color=fg); c.border=B
    ws['M3']='Seçim sütunu'; ws['M3'].fill=fill('FFF2CC'); ws['M3'].font=F(bold=True,color='0000FF'); ws['M3'].border=B
    landscape(ws)
    return last

def write_ozet(o,PL,with_fx,UL=None,keys=None,order=None):
    o.sheet_view.zoomScale=90
    for col,w in zip('ABCDEFGHIJKLMNOP',[30]+[11]*15): o.column_dimensions[col].width=w
    o['A1']='T01_0000_0000 – Proje Takip Özeti'; o['A1'].font=Font(name=FONT,bold=True,size=16,color=NAVY)
    o['A2']="Parça Listesi"+(" ve Bağlantı Özeti" if with_fx else "")+"'ndeki seçimlere ve Temin Şekli'ne göre otomatik güncellenir. Güncel BOM: 02.11.2026."
    o['A2'].font=Font(name=FONT,italic=True,size=9,color='595959')
    P="'Parça Listesi'"
    dur=f'{P}!$N${HR+1}:$N${PL}'; tem=f'{P}!$J${HR+1}:$J${PL}'; qty=f'{P}!$G${HR+1}:$G${PL}'; grp=f'{P}!$D${HR+1}:$D${PL}'; tip=f'{P}!$C${HR+1}:$C${PL}'
    def sec(row,t,h2='Satır',h3='Adet'):
        for k,v in enumerate([t,h2,h3]):
            c=o.cell(row,1+k,v); c.fill=HF; c.font=HFont; c.alignment=Alignment(horizontal='left' if k==0 else 'center')
    def line(row,label,f1,f2=None,key=None,bold=False,pct=False,bg=None):
        for i,v in enumerate([label,f1,f2],1):
            c=o.cell(row,i,v); c.font=F(bold=bold); c.border=B
            if i>1: c.alignment=Alignment(horizontal='center')
            if pct and i>1: c.number_format='0%'
        if key: b_,f_=COL[key]; o.cell(row,1).fill=fill(b_); o.cell(row,1).font=F(bold=True,color=f_)
        if bg: o.cell(row,1).fill=fill(bg)
    R0=9; sec(R0,'İmalat Parçaları')
    line(R0+1,'Üretildi',f'=COUNTIFS({dur},"Üretildi",{tem},"İmalat")',f'=SUMIFS({qty},{dur},"Üretildi",{tem},"İmalat")','Üretildi')
    line(R0+2,'Üretilmedi',f'=COUNTIFS({dur},"Üretilmedi",{tem},"İmalat")',f'=SUMIFS({qty},{dur},"Üretilmedi",{tem},"İmalat")','Üretilmedi')
    line(R0+3,'Toplam',f'=B{R0+1}+B{R0+2}',f'=C{R0+1}+C{R0+2}',bold=True)
    line(R0+4,'İlerleme',f'=IFERROR(B{R0+1}/B{R0+3},0)',f'=IFERROR(C{R0+1}/C{R0+3},0)',bold=True,pct=True)
    R1=R0+6; sec(R1,'Hazır Alım (parça + montaj)')
    for i,k in enumerate(ORD): line(R1+1+i,k,f'=COUNTIFS({dur},"{k}",{tem},"Hazır Alım")',f'=SUMIFS({qty},{dur},"{k}",{tem},"Hazır Alım")',k)
    line(R1+4,'Toplam',f'=SUM(B{R1+1}:B{R1+3})',f'=SUM(C{R1+1}:C{R1+3})',bold=True)
    line(R1+5,'Teslim oranı',f'=IFERROR(B{R1+3}/B{R1+4},0)',f'=IFERROR(C{R1+3}/C{R1+4},0)',bold=True,pct=True)
    nxt=R1+7
    if with_fx:
        BT=f"'Bağlantı Özeti'!$A${HR+1}:$A${UL}"; BQ=f"'Bağlantı Özeti'!$E${HR+1}:$E${UL}"; BD=f"'Bağlantı Özeti'!$G${HR+1}:$G${UL}"
        R2=nxt; sec(R2,'Bağlantı Elemanları','Kalem','Adet')
        types=[t for t in order if any(k[0]==t for k in keys)]
        for i,t in enumerate(types): line(R2+1+i,t,f'=COUNTIF({BT},"{t}")',f'=SUMIF({BT},"{t}",{BQ})',bg=tfill[t])
        RT=R2+1+len(types); line(RT,'Toplam',f'=SUM(B{R2+1}:B{RT-1})',f'=SUM(C{R2+1}:C{RT-1})',bold=True)
        R3=RT+2; sec(R3,'Bağlantı Elemanı Siparişi','Kalem','')
        for i,k in enumerate(ORD): line(R3+1+i,k,f'=COUNTIF({BD},"{k}")','',k)
        nxt=R3+5
    R4=nxt; sec(R4,'Diğer')
    line(R4+1,'Eksik adet satırları',f'=COUNTIF({tip},"Eksik")',f'=SUMIF({tip},"Eksik",{qty})',bg=EKF)
    line(R4+2,'Temin şekli belirtilmemiş',f'=COUNTIF({tem},"Belirtilmemiş")',f'=SUMIF({tem},"Belirtilmemiş",{qty})'); o.cell(R4+2,1).font=F(color='C00000')
    if not with_fx: pass
    else: line(R4+3,'Montajı tamamlanan montaj',f'=COUNTIF({dur},"Montajlandı")&" / "&(COUNTIF({dur},"Montajlandı")+COUNTIF({dur},"Montajlanmadı"))','')
    cards=[('A4','A5','İMALAT İLERLEMESİ',f'=B{R0+4}','0%','2E75B6'),
           ('B4:D4','B5:D5','ÜRETİLEN PARÇA (satır)',f'=B{R0+1}&" / "&B{R0+3}','@','2E75B6'),
           ('E4:G4','E5:G5','HAZIR ALIM TESLİM (satır)',f'=B{R1+3}&" / "&B{R1+4}','@','6AA84F')]
    if with_fx:
        cards+=[('H4:J4','H5:J5','BAĞLANTI ELEMANI (adet)',f'=C{RT}','#,##0','8E7CC3'),
                ('K4:M4','K5:M5','BAĞLANTI TESLİM (kalem)',f'=B{R3+3}&" / "&B{RT}','@','8E7CC3'),
                ('N4:P4','N5:P5','EKSİK ADET',f'=C{R4+1}','0','5B2C83')]
    else:
        cards+=[('H4:J4','H5:J5','TESLİM ORANI',f'=B{R1+5}','0%','6AA84F'),('K4:M4','K5:M5','EKSİK ADET',f'=C{R4+1}','0','5B2C83')]
    for lab_rng,val_rng,lab,f_,fmt,colr in cards:
        if ':' in lab_rng: o.merge_cells(lab_rng); o.merge_cells(val_rng)
        a=o[lab_rng.split(':')[0]]; v=o[val_rng.split(':')[0]]
        a.value=lab; a.font=Font(name=FONT,bold=True,size=9,color='FFFFFF'); a.alignment=Alignment(horizontal='center',vertical='center')
        v.value=f_; v.font=Font(name=FONT,bold=True,size=20,color=colr); v.number_format=fmt; v.alignment=Alignment(horizontal='center',vertical='center')
        sd=Side(style='thin',color=colr)
        for rng in (lab_rng,val_rng):
            cells=o[rng] if ':' in rng else ((o[rng],),)
            for row_ in cells:
                for c in row_:
                    c.border=Border(left=sd,right=sd,top=sd,bottom=sd)
                    if rng==lab_rng: c.fill=fill(colr)
    o.row_dimensions[4].height=20; o.row_dimensions[5].height=36
    def pie(title_,lab_ref,val_ref,colors,anchor):
        ch=PieChart(); ch.title=title_; ch.add_data(val_ref,titles_from_data=False); ch.set_categories(lab_ref)
        s=ch.series[0]
        for i,c in enumerate(colors):
            pt=DataPoint(idx=i); pt.graphicalProperties.solidFill=c; pt.graphicalProperties.line.solidFill='FFFFFF'; s.dPt.append(pt)
        dl=DataLabelList(); dl.showPercent=True; dl.showVal=True; dl.showCatName=False; dl.showSerName=False; dl.showLegendKey=False; dl.showLeaderLines=False
        ch.dataLabels=dl; ch.legend.position='r'; ch.width=11.5; ch.height=7.2; o.add_chart(ch,anchor)
    pie('İmalat Parçaları (satır)',Reference(o,min_col=1,min_row=R0+1,max_row=R0+2),Reference(o,min_col=2,min_row=R0+1,max_row=R0+2),[CH['Üretildi'],CH['Üretilmedi']],'E8')
    pie('Hazır Alım Siparişleri (satır)',Reference(o,min_col=1,min_row=R1+1,max_row=R1+3),Reference(o,min_col=2,min_row=R1+1,max_row=R1+3),[CH[k] for k in ORD],'K8')
    if with_fx:
        pie('Bağlantı Elemanları – türe göre adet',Reference(o,min_col=1,min_row=R2+1,max_row=RT-1),Reference(o,min_col=3,min_row=R2+1,max_row=RT-1),[tchart[t] for t in types],'E23')
        pie('Bağlantı Elemanı Siparişleri (kalem)',Reference(o,min_col=1,min_row=R3+1,max_row=R3+3),Reference(o,min_col=2,min_row=R3+1,max_row=R3+3),[CH[k] for k in ORD],'K23')
    G0=max(R4+6,39 if with_fx else 27)
    o.cell(G0-1,1,'Ana Gruplara Göre Durum').font=Font(name=FONT,bold=True,size=12,color=NAVY)
    for i,h in enumerate(['Ana Grup','İmalat Parça','Üretildi','Üretilmedi','İlerleme','Hazır Alım','Teslim Edildi'],1):
        c=o.cell(G0,i,h); c.font=HFont; c.fill=HF; c.border=B; c.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    o.row_dimensions[G0].height=30
    groups=[x['pno'] for x in bom if x['depth']==1 and not x['fx'] and x['ext']=='SLDASM']+['(Ana montaj)']
    r=G0+1
    for g in groups:
        vals=[g,f'=C{r}+D{r}',f'=COUNTIFS({grp},"{g}",{dur},"Üretildi",{tem},"İmalat")',f'=COUNTIFS({grp},"{g}",{dur},"Üretilmedi",{tem},"İmalat")',
              f'=IF(B{r}=0,"-",C{r}/B{r})',f'=COUNTIFS({grp},"{g}",{tem},"Hazır Alım")',f'=COUNTIFS({grp},"{g}",{dur},"Sipariş Teslim Edildi",{tem},"Hazır Alım")']
        for i,v in enumerate(vals,1):
            c=o.cell(r,i,v); c.font=base; c.border=B; c.alignment=Alignment(horizontal='center' if i>1 else 'left')
        o.cell(r,5).number_format='0%'; o.cell(r,5).font=F(bold=True); r+=1
    GL=r-1
    for i,v in enumerate(['TOPLAM',f'=SUM(B{G0+1}:B{GL})',f'=SUM(C{G0+1}:C{GL})',f'=SUM(D{G0+1}:D{GL})',f'=IF(B{r}=0,"-",C{r}/B{r})',f'=SUM(F{G0+1}:F{GL})',f'=SUM(G{G0+1}:G{GL})'],1):
        c=o.cell(r,i,v); c.font=Font(name=FONT,bold=True,color='FFFFFF'); c.fill=HF; c.border=B; c.alignment=Alignment(horizontal='center' if i>1 else 'left')
    o.cell(r,5).number_format='0%'
    o.conditional_formatting.add(f'E{G0+1}:E{GL}',DataBarRule(start_type='num',start_value=0,end_type='num',end_value=1,color='5B9BD5'))
    bar=BarChart(); bar.type='bar'; bar.grouping='stacked'; bar.overlap=100; bar.title='Ana gruplara göre imalat parçaları (satır)'
    bar.add_data(Reference(o,min_col=3,min_row=G0,max_row=GL),titles_from_data=True); bar.add_data(Reference(o,min_col=4,min_row=G0,max_row=GL),titles_from_data=True)
    bar.set_categories(Reference(o,min_col=1,min_row=G0+1,max_row=GL))
    bar.series[0].graphicalProperties.solidFill=CH['Üretildi']; bar.series[1].graphicalProperties.solidFill=CH['Üretilmedi']
    bar.x_axis.scaling.orientation='maxMin'; bar.legend.position='b'; bar.gapWidth=40; bar.y_axis.majorGridlines=None
    bar.x_axis.delete=False; bar.y_axis.delete=False; bar.x_axis.tickLblSkip=1; bar.width=17; bar.height=13.5
    o.add_chart(bar,f'I{G0}')
    o.page_setup.orientation='landscape'; o.page_setup.fitToWidth=1; o.page_setup.fitToHeight=0; o.sheet_properties.pageSetUpPr.fitToPage=True

# ===================================================================== TAKİP LİSTESİ (tam)
wb=Workbook(); ws=wb.active; ws.title='Parça Listesi'
PL=write_parts(ws,rows,with_note=True,parts_only=False)
ws2=wb.create_sheet('Bağlantı Elemanları')
ws2['A1']='Bağlantı Elemanları – Detay (montaj bazında)'; ws2['A1'].font=Font(name=FONT,bold=True,size=14,color=NAVY)
ws2['A2']='Toplam Adet = Adet × Montaj Çarpanı. Sipariş takibi "Bağlantı Özeti" sayfasındadır.'; ws2['A2'].font=Font(name=FONT,italic=True,size=9,color='595959')
header(ws2,['Ana Grup','Üst Montaj','Seviye','Tür','Açıklama','Standart','Ölçü','Çap (mm)','Boy (mm)','Adet','Montaj Çarpanı','Toplam Adet','Orijinal Ad'],[16,16,11,9,30,22,14,8,8,7,9,9,36])
fx_rows=[x for x in bom if x['fx']]; r=HR+1
for x in fx_rows:
    f=x['fx']
    vals=[x['top'] if x['depth']>1 else '(Ana montaj)',x['par'] if x['depth']>1 else 'T01_0000_0000',x['lvl'],f['t'],f['desc'],f['std'],f['size'],f['d'],f['l'],x['qty'],x['mult'],f'=J{r}*K{r}',f['orig']]
    for i,v in enumerate(vals,1):
        c=ws2.cell(r,i,v); c.font=base; c.border=B
        if i in (7,8,9,10,11,12): c.alignment=Alignment(horizontal='center')
    ws2.cell(r,4).fill=fill(tfill[f['t']]); ws2.cell(r,4).font=F(bold=True); ws2.cell(r,12).font=F(bold=True)
    ws2.cell(r,3).number_format='@'; ws2.cell(r,8).number_format='0.#'; ws2.cell(r,9).number_format='0.#'; r+=1
FL=r-1
ws2.auto_filter.ref=f'A{HR}:M{FL}'; ws2.freeze_panes=f'D{HR+1}'
ws2['A3']='Filtrelenen toplam adet:'; ws2['A3'].font=F(bold=True); ws2['C3']=f'=SUBTOTAL(109,L{HR+1}:L{FL})'
ws2['C3'].font=F(bold=True,size=11,color=NAVY); ws2['C3'].fill=fill('FFF2CC'); landscape(ws2)

ws6=wb.create_sheet('Bağlantı Özeti')
ws6['A1']='Bağlantı Elemanları – Kalem Bazında Toplam'; ws6['A1'].font=Font(name=FONT,bold=True,size=14,color=NAVY)
ws6['A2']='Her ölçü tek satır; adetler "Bağlantı Elemanları" sayfasından otomatik toplanır. Sipariş durumunu buradan takip edin.'; ws6['A2'].font=Font(name=FONT,italic=True,size=9,color='595959')
header(ws6,['Tür','Açıklama','Standart','Ölçü','Toplam Adet','Kullanıldığı Ana Gruplar','Durum','Not'],[10,32,22,14,10,60,22,40])
order={'Cıvata':0,'Somun':1,'Pim':2,'Rondela':3,'Kama':4,'Segman':5}
uniq={}
for x in fx_rows:
    f=x['fx']; k=(f['t'],f['std'],f['size'])
    u=uniq.setdefault(k,dict(desc=f['desc'],d=f['d'],l=f['l'] or 0,groups=[]))
    g=x['top'] if x['depth']>1 else '(Ana montaj)'
    if g not in u['groups']: u['groups'].append(g)
keys=sorted(uniq,key=lambda k:(order[k[0]],k[1],uniq[k]['d'],uniq[k]['l']))
std_r=f"'Bağlantı Elemanları'!$F${HR+1}:$F${FL}"; sz_r=f"'Bağlantı Elemanları'!$G${HR+1}:$G${FL}"; q_r=f"'Bağlantı Elemanları'!$L${HR+1}:$L${FL}"
r=HR+1; fx_new=[]
for k in keys:
    t,std,size=k; u=uniq[k]
    st=fx_status.get((std,size))
    if st is None: st='Sipariş Verilmedi'; fx_new.append(k)
    note={'DIN 912 / ISO 4762':'DIN 912 ve ISO 4762 aynı cıvata – birleştirildi','DIN 125-A / ISO 7089':'DIN 125-A ve ISO 7089 aynı rondela – birleştirildi'}.get(std,'')
    vals=[t,u['desc'],std,size,f'=SUMIFS({q_r},{std_r},"{std}",{sz_r},"{size}")',', '.join(u['groups']),st,note]
    for i,v in enumerate(vals,1):
        c=ws6.cell(r,i,v); c.font=base; c.border=B; c.alignment=Alignment(vertical='center',wrap_text=(i==6))
        if i in (4,5): c.alignment=Alignment(horizontal='center',vertical='center')
    ws6.cell(r,1).fill=fill(tfill[t]); ws6.cell(r,1).font=F(bold=True); ws6.cell(r,5).font=F(bold=True,size=11); r+=1
UL=r-1
dv=DataValidation(type='list',formula1='"'+','.join(ORD)+'"',allow_blank=True); ws6.add_data_validation(dv); dv.add(f'G{HR+1}:G{UL}')
status_cf(ws6,f'G{HR+1}:G{UL}',f'G{HR+1}')
ws6.auto_filter.ref=f'A{HR}:H{UL}'; ws6.freeze_panes=f'A{HR+1}'
ws6['A3']='Filtrelenen toplam adet:'; ws6['A3'].font=F(bold=True); ws6['C3']=f'=SUBTOTAL(109,E{HR+1}:E{UL})'
ws6['C3'].font=F(bold=True,size=11,color=NAVY); ws6['C3'].fill=fill('FFF2CC'); landscape(ws6)

o=wb.create_sheet('Özet',0); write_ozet(o,PL,True,UL,keys,order)
for s in wb.worksheets: s.sheet_view.showGridLines=False
for s,cl in zip(wb.worksheets,[NAVY,'2E75B6','70AD47','548235']): s.sheet_properties.tabColor=cl
wb.save(OUT_T)

# ===================================================================== PARÇA TAKİP (sadece parça + özet)
prow=[x for x in rows if not x['in_hazir'] and not (x['typ']=='Montaj' and x['temin']!='Hazır Alım')]
wb2=Workbook(); w=wb2.active; w.title='Parça Listesi'
PL2=write_parts(w,prow,with_note=False,parts_only=True)
o2=wb2.create_sheet('Özet',0); write_ozet(o2,PL2,False)
for s in wb2.worksheets: s.sheet_view.showGridLines=False
o2.sheet_properties.tabColor=NAVY; w.sheet_properties.tabColor='2E75B6'
wb2.save(OUT_P)

print('takip rows',len(rows),'parça rows',len(prow),'fx rows',len(fx_rows),'uniq',len(keys),'fx_new',fx_new)
print('removed',removed)
print('new',[x['pno'] for x in rows if x['new']])
