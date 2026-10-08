"""Step5-②半球判别: CLIP判图的半球 vs 国家真值半球; 若准则作低margin候选约束。"""
import json,os,sys
import numpy as np
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from app.geokb.local_engine import _load_engine, COUNTRIES, country_scores_feat, encode_streetclip
from app.geokb.geo_dims import GEO_DIMS

def norm(s):
    n=s.strip().lower()
    return {"czech republic":"czechia","usa":"united states","uk":"united kingdom"}.get(n,n)

# 国家→半球
def hemi_of_country(c):
    d=GEO_DIMS.get(c)
    if not d: return '?'
    h=d.get('hemisphere',['?'])[0]
    return h  # N/S/T

model,proc,_=_load_engine()
d=np.load('step5_imgfeats.npz',allow_pickle=True)
feats=d['feats']; fns=list(d['fns'])
cats=json.load(open('bench_final/categories.json',encoding='utf-8'))

# CLIP 半球判别
texts=["a photo taken in the northern hemisphere",
       "a photo taken in the southern hemisphere",
       "a photo showing a tropical location near the equator"]
inp=proc(text=texts,return_tensors='pt',padding=True)
with torch.no_grad(): tf=model.get_text_features(**inp)
tf=(tf/tf.norm(dim=-1,keepdim=True)).numpy()

H=['N','S','T']
ok=wrong=tropical_truth=0
conf_matrix={}
for i,fn in enumerate(fns):
    truth_c=cats[fn]['country']
    th=hemi_of_country(truth_c)
    sims=tf@feats[i]
    ph=H[int(sims.argmax())]
    key=(th,ph)
    conf_matrix[key]=conf_matrix.get(key,0)+1
    if th=='T': tropical_truth+=1; continue  # 热带真值不评
    if ph==th: ok+=1
    else: wrong+=1
tot=ok+wrong
print(f'半球判别(排除热带真值{tropical_truth}张): {ok}/{tot} = {100*ok/tot:.1f}%')
print('混淆(真值,预测):',{f'{k}':v for k,v in sorted(conf_matrix.items())})

# 应用约束: 低margin图(margin<0.04), 候选只留半球匹配国家(热带图不约束)
# 找低margin图的国家top1半球错误情况
sc_full={}
for i,fn in enumerate(fns):
    feat=feats[i]
    # 全量分数需要文本塔(已缓存 nat_tf)
    pass
_,_,nat_tf=_load_engine()
nat_np=nat_tf.numpy() if hasattr(nat_tf,'numpy') else None
# nat_tf shape: (101*3, dim) → 重组
dim=nat_np.shape[1]
nat3=nat_np.reshape(len(COUNTRIES),3,dim)
natm=nat3.mean(1); natm=natm/np.linalg.norm(natm,axis=1,keepdims=True)

saved=rescued=killed=0
for i,fn in enumerate(fns):
    sims=natm@feats[i]
    order=np.argsort(-sims)
    margin=float(sims[order[0]]-sims[order[1]])
    if margin>=0.04: continue
    # CLIP半球
    hs=tf@feats[i]; ph=H[int(hs.argmax())]
    if ph=='T': continue  # 热带不约束
    truth_c=cats[fn]['country']; th=hemi_of_country(truth_c)
    # 半球约束后的新top1
    for j in order:
        c=COUNTRIES[int(j)]
        ch=hemi_of_country(c)
        if ch=='T' or ch==ph:
            new_pred=c; break
    old_pred=COUNTRIES[int(order[0])]
    o_ok=norm(old_pred)==norm(truth_c); n_ok=norm(new_pred)==norm(truth_c)
    saved+=1
    if not o_ok and n_ok: rescued+=1
    if o_ok and not n_ok: killed+=1
print(f'\n低margin(<0.04)且非热带预测的图: {saved}张')
print(f'半球约束: 救回 {rescued} / 误杀 {killed} / 净 {rescued-killed}')
