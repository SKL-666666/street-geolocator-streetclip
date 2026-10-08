"""快速两测: 测1复核国家 + 测2城市模型对比。零新模型。"""
import sys,os,json,io,time
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from PIL import Image
from app.geokb import local_engine as le

def norm(s): return s.strip().lower()

# ========== 测2: 判城市 (eval_kartaview 32张4城) ==========
print("="*50)
print("测2: 城市模型对比 (eval_kartaview 32张4城)")
print("="*50)
EVAL='../street-geolocator-streetclip/backend/data/eval_kartaview'
ek=json.load(open(os.path.join(EVAL,'metadata.json'),encoding='utf-8'))

# 加载两模型
sc_model,sc_proc,sc_nat_tf=le._load_engine()          # StreetCLIP
city_model,city_pre=le._load_city_engine()            # CLIP-B/16
# StreetCLIP 判城市的文本: 用城市名prompt
def sc_city_score(pil, city):
    texts=[f"a street view photo taken in {city}", f"a photo of {city}", f"the city of {city}"]
    inp=sc_proc(text=texts,return_tensors='pt',padding=True)
    with torch.no_grad(): tf=sc_model.get_text_features(**inp)
    tf=tf/tf.norm(dim=-1,keepdim=True)
    iinp=sc_proc(images=pil,return_tensors='pt')
    with torch.no_grad(): f=sc_model.get_image_features(**iinp)
    f=f/f.norm(dim=-1,keepdim=True)
    return float((f@tf.T).mean())

sc_hit=cb_hit=total=0
t_sc=t_cb=0
for row in ek:
    fp=os.path.join(EVAL, os.path.basename(row['file']))
    if not os.path.exists(fp): continue
    truth=row['city']
    pil=Image.open(fp).convert('RGB')
    # 真值只有4城: Paris/Madrid/Rome/Vienna, 在这4城里比
    cities=['Paris','Madrid','Rome','Vienna']
    # StreetCLIP判城市
    t0=time.time()
    sc_scores={c:sc_city_score(pil,c) for c in cities}
    t_sc+=time.time()-t0
    sc_pred=max(sc_scores,key=sc_scores.get)
    # CLIP-B/16判城市 (用项目classify_cities, 但限定这4城)
    t0=time.time()
    try:
        data=open(fp,'rb').read()
        # 直接用CLIP-B/16文本匹配这4城
        import open_clip as oc
        texts=[f"a street view photo taken in {c}" for c in cities]
        with torch.no_grad():
            tf=city_model.encode_text(oc.tokenize(texts))
            tf=tf/tf.norm(dim=-1,keepdim=True)
            x=city_pre(pil).unsqueeze(0)
            f=city_model.encode_image(x)
            f=f/f.norm(dim=-1,keepdim=True)
            sims=(f@tf.T).squeeze(0)
        cb_pred=cities[int(sims.argmax())]
    except Exception as e:
        cb_pred='?'
    t_cb+=time.time()-t0
    total+=1
    if norm(sc_pred)==norm(truth): sc_hit+=1
    if norm(cb_pred)==norm(truth): cb_hit+=1

print(f"StreetCLIP 判城市: {sc_hit}/{total} = {100*sc_hit/total:.1f}%  ({t_sc/total*1000:.0f}ms/张)")
print(f"CLIP-B/16  判城市: {cb_hit}/{total} = {100*cb_hit/total:.1f}%  ({t_cb/total*1000:.0f}ms/张)")

# ========== 测1: 复核国家 (margin<0.02的图) ==========
print()
print("="*50)
print("测1: StreetCLIP换prompt复核国家 (低置信图)")
print("="*50)
sc2=json.load(open('streetclip_scores_v2.json',encoding='utf-8'))
# 低置信图
low=[fn for fn,v in sc2.items() if v['p1']-v['p2']<0.02]
print(f"低置信(margin<0.02)图: {len(low)}张, StreetCLIP原判对{sum(1 for fn in low if norm(sc2[fn]['pred'])==norm(sc2[fn]['truth']))}张")

# 复核prompt: 更详细的地理描述
RECHECK_TEMPLATES=[
    "a street view photo clearly showing {c} with local road signs, language, and architecture",
    "a photo taken in {c}, recognizable by climate, vegetation, and building style",
    "the landscape and road infrastructure typical of {c}",
]
def sc_recheck(pil, countries):
    texts=[t.format(c=c) for c in countries for t in RECHECK_TEMPLATES]
    inp=sc_proc(text=texts,return_tensors='pt',padding=True)
    with torch.no_grad(): tf=sc_model.get_text_features(**inp)
    tf=tf/tf.norm(dim=-1,keepdim=True)
    iinp=sc_proc(images=pil,return_tensors='pt')
    with torch.no_grad(): f=sc_model.get_image_features(**iinp)
    f=f/f.norm(dim=-1,keepdim=True)
    sims=(f@tf.T).squeeze(0).view(len(countries),len(RECHECK_TEMPLATES)).mean(1)
    return {c:float(s) for c,s in zip(countries,sims)}

# 对低置信图: 复核=重新用详细prompt给全101国打分, 取Top1
rescued=wrong_first=0
detail=[]
for fn in low:
    v=sc2[fn]
    truth=v['truth']; first_pred=v['pred']
    first_ok=norm(first_pred)==norm(truth)
    p='bench_final/'+fn
    if not os.path.exists(p): continue
    pil=Image.open(p).convert('RGB')
    # 所有国家(用第一次的top候选池太小, 用全101国重打)
    all_countries=[c['label'] for c in le.COUNTRIES] if hasattr(le,'COUNTRIES') else None
    if all_countries is None:
        from app.geokb.local_engine import COUNTRIES as all_countries
    recheck=sc_recheck(pil, all_countries)
    re_pred=max(recheck,key=recheck.get)
    re_ok=norm(re_pred)==norm(truth)
    if not first_ok and re_ok: rescued+=1
    if first_ok and not re_ok: wrong_first+=1
    detail.append((fn,truth,first_pred,first_ok,re_pred,re_ok))

print(f"复核用详细prompt重打全国家:")
print(f"  原错复核对(救回): {rescued}")
print(f"  原对复核错(误杀): {wrong_first}")
print(f"  净变化: {rescued-wrong_first} (原对{sum(1 for fn in low if norm(sc2[fn]['pred'])==norm(sc2[fn]['truth']))}张)")
print()
print("样例(前8):")
for fn,truth,fp_,fok,rp,rok in detail[:8]:
    print(f"  {fn[:30]:30s} 真值={truth[:10]:10s} 原={fp_[:10]:10s}{'✓' if fok else '✗'} 复核={rp[:10]:10s}{'✓' if rok else '✗'}")
