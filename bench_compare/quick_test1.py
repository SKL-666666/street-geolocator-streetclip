import sys,os,json
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from PIL import Image
from app.geokb import local_engine as le
from app.geokb.local_engine import COUNTRIES
def norm(s): return s.strip().lower()
sc2=json.load(open('streetclip_scores_v2.json',encoding='utf-8'))
low=[fn for fn,v in sc2.items() if v['p1']-v['p2']<0.02]
orig_ok=sum(1 for fn in low if norm(sc2[fn]['pred'])==norm(sc2[fn]['truth']))
print(f"低置信图 {len(low)}张, 原判对 {orig_ok}")
model,proc,_=le._load_engine()
RECHECK=[
 "a street view photo clearly showing {c} with local road signs, language, and architecture",
 "a photo taken in {c}, recognizable by climate, vegetation, and building style",
 "the landscape and road infrastructure typical of {c}",
]
# 文本编码一次(101国x3)复用
texts=[t.format(c=c) for c in COUNTRIES for t in RECHECK]
inp=proc(text=texts,return_tensors='pt',padding=True)
with torch.no_grad(): tf=model.get_text_features(**inp)
tf=tf/tf.norm(dim=-1,keepdim=True)
tf=tf.view(len(COUNTRIES),len(RECHECK),-1).mean(1)
tf=tf/tf.norm(dim=-1,keepdim=True)
rescued=killed=0
detail=[]
for fn in low:
    v=sc2[fn]; truth=v['truth']; fp_=v['pred']
    fok=norm(fp_)==norm(truth)
    p='bench_final/'+fn
    if not os.path.exists(p): continue
    pil=Image.open(p).convert('RGB')
    iinp=proc(images=pil,return_tensors='pt')
    with torch.no_grad(): f=model.get_image_features(**iinp)
    f=f/f.norm(dim=-1,keepdim=True)
    sims=(f@tf.T).squeeze(0)
    rp=COUNTRIES[int(sims.argmax())]
    rok=norm(rp)==norm(truth)
    if not fok and rok: rescued+=1
    if fok and not rok: killed+=1
    detail.append((fn,truth,fp_,fok,rp,rok))
print(f"复核(详细prompt重打101国): 救回 {rescued}, 误杀 {killed}, 净 {rescued-killed}")
print(f"→ 低置信段从 {orig_ok} 对 → {orig_ok+rescued-killed} 对")
print("样例:")
for fn,truth,fp_,fok,rp,rok in detail[:12]:
    print(f"  真值={truth[:11]:11s} 原={fp_[:11]:11s}{'✓' if fok else '✗'} 复核={rp[:11]:11s}{'✓' if rok else '✗'}")
