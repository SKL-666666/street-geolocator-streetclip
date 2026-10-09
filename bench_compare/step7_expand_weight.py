"""Step7: ①COUNTRIES 101→130(补谷歌街景有但缺的29国) ②按GSV照片量级加权。A/B验证。"""
import json,os,sys
import numpy as np
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
import torch
from PIL import Image
from app.geokb.local_engine import _load_engine, TEMPLATES

def norm(s):
    n=s.strip().lower()
    return {"czech republic":"czechia","usa":"united states","uk":"united kingdom",
            "ivory coast":"ivory coast","cote divoire":"ivory coast"}.get(n,n)

# ---- 补29国 ----
ADD29=["Luxembourg","Liechtenstein","Andorra","Monaco","Malta","Cyprus","Georgia",
"Azerbaijan","Armenia","Bahrain","Kuwait","Mauritius","Fiji","Bhutan","Brunei",
"Madagascar","Mozambique","Uganda","Zambia","Zimbabwe","Botswana","Namibia",
"Rwanda","Ivory Coast","Cameroon","Angola","Greenland","Faroe Islands","Seychelles"]
# GSV照片量级分级权重(1=极少 ... 5=极多), 基于公开报道的GSV分布量级
W_HIGH={"United States":5,"Japan":5,"Germany":5,"United Kingdom":5,"France":5,"Italy":5,
"Spain":5,"Canada":5,"Australia":5,"Brazil":5,"Russia":5,"China":5,"India":5,"Netherlands":5}
W_MIDHIGH={"South Korea":4,"Taiwan":4,"Thailand":4,"Mexico":4,"Turkey":4,"Poland":4,
"Sweden":4,"Norway":4,"Denmark":4,"Finland":4,"Austria":4,"Switzerland":4,"Portugal":4,
"Greece":4,"Czechia":4,"Belgium":4,"Israel":4,"Singapore":4,"Malaysia":4,"Indonesia":4,
"Argentina":4,"Chile":4,"Colombia":4,"Peru":4,"South Africa":4,"Egypt":4,"New Zealand":4,"Ireland":4}
W_MID={"Ukraine":3,"Romania":3,"Hungary":3,"Croatia":3,"Bulgaria":3,"Serbia":3,"Slovakia":3,
"Vietnam":3,"Philippines":3,"Saudi Arabia":3,"UAE":3,"Morocco":3,"Kenya":3,"Nigeria":3,
"Ecuador":3,"Venezuela":3,"Kazakhstan":3,"Iran":3,"Cuba":3,"Pakistan":3}
# 其余默认2, 极少1
W_LOW={"Madagascar":1,"Mozambique":1,"Uganda":1,"Zambia":1,"Zimbabwe":1,"Botswana":1,
"Namibia":1,"Rwanda":1,"Cameroon":1,"Angola":1,"Greenland":1,"Faroe Islands":1,
"Mauritius":1,"Fiji":1,"Bhutan":1,"Seychelles":1,"Liechtenstein":1,"Andorra":1,
"Monaco":1,"Malta":1,"Cyprus":2,"Georgia":2,"Azerbaijan":2,"Armenia":2,
"Bahrain":2,"Kuwait":2,"Brunei":2,"Ivory Coast":2,"Papua New Guinea":1,
"Ethiopia":2,"Tanzania":2,"Ghana":2,"Senegal":2,"Bolivia":2,"Paraguay":2,
"Uruguay":2,"Laos":2,"Cambodia":2,"Myanmar":2,"Nepal":2,"Sri Lanka":2,
"Bangladesh":2,"Mongolia":2,"Uzbekistan":2,"Kyrgyzstan":1,"Tajikistan":1}

def weight(c):
    if c in W_HIGH: return 5
    if c in W_MIDHIGH: return 4
    if c in W_MID: return 3
    if c in W_LOW: return W_LOW[c]
    return 2

model,proc,nat_tf=_load_engine()
# 图特征
cats=json.load(open('bench_final/categories.json',encoding='utf-8'))
fns=list(cats.keys())
CACHE='step5_imgfeats.npz'
feats=np.load(CACHE,allow_pickle=True)['feats']
nat_np=nat_tf.numpy(); dim=nat_np.shape[1]
# 原101国文本分数(已有) + 扩展国(新编码文本)
from app.geokb.local_engine import COUNTRIES as C101
C_ALL=C101+ADD29
# 编码新增29国文本(3模板均值)
texts=[t.replace("{}", c) for c in ADD29 for t in TEMPLATES]
inp=proc(text=texts,return_tensors='pt',padding=True)
with torch.no_grad(): tf2=model.get_text_features(**inp)
tf2=(tf2/tf2.norm(dim=-1,keepdim=True)).numpy().reshape(len(ADD29),len(TEMPLATES),-1).mean(1)
tf2=tf2/np.linalg.norm(tf2,axis=1,keepdims=True)
# 原101国均值
natm=nat_np.reshape(len(C101),len(TEMPLATES),-1).mean(1)
natm=natm/np.linalg.norm(natm,axis=1,keepdims=True)
# 拼接130国
allm=np.vstack([natm,tf2])

def evaluate(C,use_weight):
    ok=0
    M=allm[:len(C)]  # 只用对应国家数的行
    for i,fn in enumerate(fns):
        sims=M@feats[i]
        if use_weight:
            w=np.array([weight(c) for c in C],dtype=np.float32)
            sims=sims*(1+0.05*(w-w.mean()))  # 轻微加权(±), 不淹没相似度
        pred=C[int(sims.argmax())]
        if norm(pred)==norm(cats[fn]['country']): ok+=1
    return ok

n=len(fns)
r_base=evaluate(C101,False)
r_29=evaluate(C_ALL,False)
r_29w=evaluate(C_ALL,True)
r_101w=evaluate(C101,True)
print(f'① 原101国基线:        {r_base}/{n} = {100*r_base/n:.1f}%')
print(f'② 101+29=130国:       {r_29}/{n} = {100*r_29/n:.1f}%  ({r_29-r_base:+d})')
print(f'③ 130国+GSV加权:      {r_29w}/{n} = {100*r_29w/n:.1f}%  ({r_29w-r_base:+d})')
print(f'④ 101国+GSV加权:      {r_101w}/{n} = {100*r_101w/n:.1f}%  ({r_101w-r_base:+d})')
