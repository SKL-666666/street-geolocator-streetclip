"""Step5-③车道方向: CLIP判行驶方向 vs 国家真值driving_side; 低margin约束。"""
import json,os,sys
import numpy as np
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from app.geokb.local_engine import _load_engine, COUNTRIES
# driving_side 映射
from importlib import import_module
mod=import_module('app.geokb.countries')
SIDE={}
for row in getattr(mod,'COUNTRY_SEED',[]) or []:
    if isinstance(row,dict) and 'name' in row:
        SIDE[row['name']]=row.get('driving_side')
# 备用: 直接解析模块级数据结构
if not SIDE:
    import re
    src=open('../street-geolocator-streetclip/backend/app/geokb/countries.py',encoding='utf-8').read()
    for m in re.finditer(r'"name":\s*"([^"]+)".*?"driving_side":\s*"(left|right)"',src,re.S):
        SIDE[m.group(1)]=m.group(2)
print('驾驶侧数据国数:',len(SIDE))
def norm(s):
    n=s.strip().lower()
    return {"czech republic":"czechia","usa":"united states","uk":"united kingdom"}.get(n,n)
model,proc,_=_load_engine()
d=np.load('step5_imgfeats.npz',allow_pickle=True)
feats=d['feats']; fns=list(d['fns'])
cats=json.load(open('bench_final/categories.json',encoding='utf-8'))
# CLIP车道判别
texts=["traffic driving on the left side of the road",
       "traffic driving on the right side of the road",
       "a road with vehicles driving on the left",
       "a road with vehicles driving on the right"]
inp=proc(text=texts,return_tensors='pt',padding=True)
with torch.no_grad():
    tf=model.get_text_features(**inp)
tf=(tf/tf.norm(dim=-1,keepdim=True)).numpy()
ok=wrong=nodata=0
for i,fn in enumerate(fns):
    tc=cats[fn]['country']; side=SIDE.get(tc.replace('United Kingdom','United Kingdom'))
    if not side: nodata+=1; continue
    sims=tf@feats[i]
    # left组(0,2)均值 vs right组(1,3)均值
    pl=float(sims[[0,2]].mean()); pr=float(sims[[1,3]].mean())
    ph='left' if pl>pr else 'right'
    if ph==side: ok+=1
    else: wrong+=1
print(f'车道判别(有真值侧): {ok}/{ok+wrong} = {100*ok/(ok+wrong):.1f}% (无数据{nodata}张)')
# 低margin约束
_,_,nat_tf=_load_engine()
nat_np=nat_tf.numpy(); dim=nat_np.shape[1]
natm=nat_np.reshape(len(COUNTRIES),3,dim).mean(1)
natm=natm/np.linalg.norm(natm,axis=1,keepdims=True)
rescued=killed=applied=0
for i,fn in enumerate(fns):
    sims=natm@feats[i]; order=np.argsort(-sims)
    if float(sims[order[0]]-sims[order[1]])>=0.04: continue
    tc=cats[fn]['country']; tside=SIDE.get(tc)
    if not tside: continue
    hs=tf@feats[i]
    ph='left' if float(hs[[0,2]].mean())>float(hs[[1,3]].mean()) else 'right'
    new_pred=None
    for j in order:
        c=COUNTRIES[int(j)]; s=SIDE.get(c)
        if s is None or s==ph: new_pred=c; break
    if new_pred is None: continue
    applied+=1
    old=COUNTRIES[int(order[0])]
    o_ok=norm(old)==norm(tc); n_ok=norm(new_pred)==norm(tc)
    if not o_ok and n_ok: rescued+=1
    if o_ok and not n_ok: killed+=1
print(f'低margin车道约束: 应用{applied}张, 救回{rescued} 误杀{killed} 净{rescued-killed}')
