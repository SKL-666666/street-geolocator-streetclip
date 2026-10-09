"""城市池大小A/B: 用 eval_kartaview 32张(4真值城) 测 SC判城市 vs 池大小。
城市文本每档编码一次(缓存), 图特征复用 step5_imgfeats 不适用(不同图集) → 现编码。"""
import json,os,sys,time
import numpy as np
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from PIL import Image
from app.geokb.local_engine import _load_engine, _SC_CITY_TEMPLATES, _country_cities
from app.geokb.cities import CITY_COORDS
from app.geokb.countries import COUNTRY_ALIASES

def pool_of(country, n):
    """指定池大小的该国城市(按CITY_COORDS顺序, 与_country_cities同序)。"""
    country=COUNTRY_ALIASES.get(country,country)
    cities=[c for c,v in CITY_COORDS.items() if v[2]==country]
    return cities[:n] if n else cities

EVAL='../street-geolocator-streetclip/backend/data/eval_kartaview'
rows=json.load(open(os.path.join(EVAL,'metadata.json'),encoding='utf-8'))
model,proc,_=_load_engine()
# 图特征
feats=[]; truths=[]
t0=time.time()
with torch.no_grad():
    for r in rows:
        fp=os.path.join(EVAL,os.path.basename(r['file']))
        if not os.path.exists(fp): continue
        img=Image.open(fp).convert('RGB')
        inp=proc(images=img,return_tensors='pt')
        f=model.get_image_features(**inp)
        feats.append((f/f.norm()).numpy()[0])
        truths.append((r['country'],r['city']))
print(f'编码{len(feats)}张 {time.time()-t0:.0f}s')
# 国家真值池(端到端前提: 用真值国家隔离, 只测城市这级)
def text_feats(cities):
    texts=[t.format(c=c) for c in cities for t in _SC_CITY_TEMPLATES]
    inp=proc(text=texts,return_tensors='pt',padding=True)
    with torch.no_grad(): tf=model.get_text_features(**inp)
    tf=(tf/tf.norm(dim=-1,keepdim=True)).numpy()
    return tf.reshape(len(cities),len(_SC_CITY_TEMPLATES),-1).mean(1)

print()
print(f'{"池大小":>8} {"Top1命中":>10} {"Top3命中":>10} {"文本编码(首国)":>14}')
for n in [10,30,50,100,200,9999]:
    ok1=ok3=0; enc_t=0
    # 每国编码池(4国)
    pools={}
    for country,_ in truths:
        if country not in pools:
            cities=pool_of(country, min(n,10**9))
            if n>=9999: cities=pool_of(country,0)
            t0=time.time(); tf=text_feats(cities); enc_t+=time.time()-t0
            pools[country]=(cities,tf)
    for idx, (country, city) in enumerate(truths):
        cities, tf = pools[country]
        f = feats[idx]
        sims = tf @ f
        order = np.argsort(-sims)
        pred = [cities[i] for i in order[:3]]
        if pred[0] == city: ok1 += 1
        if city in pred: ok3 += 1
    N=len(truths)
    print(f'{len(pools[truths[0][0]][0]):>8} {ok1}/{N}={100*ok1/N:>5.1f}% {ok3}/{N}={100*ok3/N:>5.1f}% {enc_t/4*1000:>10.0f}ms/国')
