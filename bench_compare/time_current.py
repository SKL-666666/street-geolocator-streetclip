"""当前架构耗时: StreetCLIP(国家) + CLIP-B/16(城市) 两模型各编码。"""
import sys,os,time
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
from PIL import Image
import torch
pil=Image.open('bench_final/FR_paris_0.jpg').convert('RGB')
from app.geokb import local_engine as le
# StreetCLIP
t0=time.time(); model,proc,tf=le._load_engine(); t_sload=time.time()-t0
inp=proc(images=pil,return_tensors='pt')
t0=time.time()
with torch.no_grad(): f1=model.get_image_features(**inp)
t_sc=time.time()-t0
# CLIP-B/16: 项目用什么加载? 看 _encode_image
import inspect
src=inspect.getsource(le._encode_image)
print('_encode_image 用的模型:', 'open_clip' if 'open_clip' in src else ('CLIPModel' if 'CLIPModel' in src else '?'))
# 尝试用项目的方式编码
t0=time.time()
try:
    f2=le._encode_image(open('bench_final/FR_paris_0.jpg','rb').read())
    t_cb=time.time()-t0
except Exception as e:
    t_cb=-1; print('CLIP-B/16 编码失败:',e)
print()
print('=== 当前架构(两模型各编码)单图耗时 ===')
print(f'StreetCLIP编码: {t_sc*1000:.0f}ms')
print(f'CLIP-B/16编码: {t_cb*1000:.0f}ms' if t_cb>0 else 'CLIP-B/16: 失败')
if t_cb>0: print(f'合计(串行): {(t_sc+t_cb)*1000:.0f}ms')
