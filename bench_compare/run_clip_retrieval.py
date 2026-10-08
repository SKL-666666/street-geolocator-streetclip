"""公平对比: CLIP特征 leave-one-out 检索 (与 run_dinov2.py 同条件)。
用 StreetCLIP 的图像特征(与文本无关, 纯检索), 看 vs DINOv2 谁强。
"""
import json,os,sys,time
import numpy as np
HERE=os.path.dirname(os.path.abspath(__file__))
BENCH=os.path.join(HERE,'bench_final')
K=5
def norm_country(n):
    n=n.strip().lower()
    a={"uk":"united kingdom","usa":"united states","czech republic":"czechia","russian federation":"russia","turkiye":"turkey","republic of korea":"south korea"}
    return a.get(n,n)
def main():
    sys.path.insert(0,os.path.abspath(os.path.join(HERE,'..','street-geolocator-streetclip','backend')))
    from app.geokb import local_engine as le
    import torch
    from PIL import Image
    t0=time.time()
    model,proc,_=le._load_engine()
    load_s=time.time()-t0
    print(f'[load] StreetCLIP img-encoder {load_s:.1f}s',file=sys.stderr)
    cats=json.load(open(os.path.join(BENCH,'categories.json'),encoding='utf-8'))
    files=list(cats.keys())
    feats=[];infer=[]
    with torch.no_grad():
        for fn in files:
            img=Image.open(os.path.join(BENCH,fn)).convert('RGB')
            inp=proc(images=img,return_tensors='pt')
            t1=time.time()
            f=model.get_image_features(**inp)
            infer.append((time.time()-t1)*1000)
            f=f.squeeze(0); f=f/f.norm(); feats.append(f.numpy())
    D=np.stack(feats)
    print(f'[extract] {len(D)} in {time.time()-t0:.0f}s',file=sys.stderr)
    total=correct=0; per_cat={}
    for i,fn in enumerate(files):
        truth=cats[fn]['country']
        sims=D@D[i]; sims[i]=-999
        top=np.argsort(-sims)[:K]
        votes={}
        for j in top:
            c=cats[files[j]]['country']; votes[c]=votes.get(c,0)+float(max(sims[j],0))
        pred=max(votes.items(),key=lambda x:x[1])[0] if votes else '?'
        hit=norm_country(pred)==norm_country(truth)
        total+=1; correct+=1 if hit else 0
        cat=cats[fn]['cat']; per_cat.setdefault(cat,[0,0]); per_cat[cat][1]+=1; per_cat[cat][0]+=1 if hit else 0
        if not hit: print(f'  [miss] {fn}: {pred} | {truth}',file=sys.stderr)
    infer.sort()
    print('\n===== CLIP(StreetCLIP图像特征) leave-one-out检索 =====')
    for c,(a,b) in per_cat.items(): print(f'  {c:6s}: {a}/{b} = {100*a/b:.1f}%')
    print(f'  总计: {correct}/{total} = {100*correct/total:.1f}%')
    print(f'  单张: 平均{sum(infer)/len(infer):.0f}ms')
main()
