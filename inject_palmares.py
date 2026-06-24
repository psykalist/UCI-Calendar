import sqlite3, json, os
from datetime import datetime, timezone

DB  = r"C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results\cycling.db"
DAT = r"C:\DataDrive\Documents\Claude\Projects\UCI Calendar & Results\data.json"

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
c = conn.cursor()
c.execute("SELECT race_slug,year,winner,winner_slug,second,second_slug,third,third_slug FROM race_palmares ORDER BY race_slug,year DESC")
pbr = {}
for row in c.fetchall():
    pbr.setdefault(row['race_slug'],[]).append(dict(row))
conn.close()

if not pbr:
    print('No palmares rows found in cycling.db — skipping injection')
    raise SystemExit(0)

with open(DAT,'r',encoding='utf-8') as f: content=f.read()
decoder=json.JSONDecoder(); d,_=decoder.raw_decode(content)
for bucket in ('live','upcoming','recent'):
    for race in d.get(bucket,[]):
        slug=race.get('slug','')
        if slug in pbr: race['palmares']=pbr[slug]
d['palmares']=pbr
d['scraped_at']=datetime.now(timezone.utc).isoformat()
tmp=DAT+'.tmp'
with open(tmp,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,separators=(',',':'))
os.replace(tmp,DAT)
print(f'palmares injected: {len(pbr)} races')
