"""Step5-①提示词优化: 多组国家模板在bench_final上A/B(图特征缓存复用)。"""
import json,os,sys,time
import numpy as np
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from PIL import Image
from app.geokb.local_engine import _load_engine, COUNTRIES
def norm(s):
    n=s.strip().lower()
    return {"czech republic":"czechia","usa":"united states","uk":"united kingdom"}.get(n,n)
CACHE='step5_imgfeats.npz'
model,proc,_=_load_engine()
if os.path.exists(CACHE):
    d=np.load(CACHE,allow_pickle=True)
    feats=d['feats']; fns=list(d['fns'])
    print(f'缓存命中 {len(fns)}张')
else:
    cats=json.load(open('bench_final/categories.json',encoding='utf-8'))
    fns=list(cats.keys()); feats=[]
    with torch.no_grad():
        for fn in fns:
            img=Image.open('bench_final/'+fn).convert('RGB')
            inp=proc(images=img,return_tensors='pt')
            f=model.get_image_features(**inp)
            feats.append((f/f.norm()).numpy()[0])
    np.savez_compressed(CACHE,feats=np.stack(feats),fns=np.array(fns))
    print(f'提取 {len(fns)}张特征')
truths={fn:json.load(open('bench_final/categories.json',encoding='utf-8'))[fn]['country'] for fn in fns}
truths={fn:norm(t) for fn,t in truths.items()}

GROUPS={
 'T0当前3模板': ["a street view photo taken in {}", "a photo taken in {}", "a street in {}"],
 'T1丰富5模板': ["a street view photo taken in {}", "a photo taken in {}", "a street in {}",
              "road and buildings typical of {}", "an urban scene in {}"],
 'T2地理细节': ["a street view photo taken in {}, showing road signs and local architecture",
             "typical street scene in {}, with local vegetation and building style",
             "a photo taken in {}, recognizable by climate and landscape"],
 'T3国家+大陆': None,  # 需要大陆信息, 稍后
 'T4简洁': ["a photo taken in {}", "in {}"],
 'T5口语GeoGuessr': ["this photo was taken in {}", "location: {}", "a random street in {}"],
}
def evaluate(templates):
    texts=[t.replace("{}", c) for c in COUNTRIES for t in templates]
    inp=proc(text=texts,return_tensors='pt',padding=True)
    with torch.no_grad(): tf=model.get_text_features(**inp)
    tf=tf/tf.norm(dim=-1,keepdim=True).numpy() if hasattr(tf,'norm') else tf
    tf=tf.view(len(COUNTRIES),len(templates),-1).numpy()
    tfm=tf.mean(1); tfm=tfm/np.linalg.norm(tfm,axis=1,keepdims=True)
    ok=0
    for i,fn in enumerate(fns):
        sims=tfm@feats[i]
        pred=COUNTRIES[int(sims.argmax())]
        if norm(pred)==truths[fn]: ok+=1
    return ok
print()
base=None
for name,tpls in GROUPS.items():
    if tpls is None: continue
    t0=time.time(); ok=evaluate(tpls); dt=time.time()-t0
    if base is None: base=ok
    delta=ok-base
    print(f'{name:16s}: {ok}/{len(fns)} = {100*ok/len(fns):.1f}%  ({delta:+d} vs T0, {dt:.0f}s)')
