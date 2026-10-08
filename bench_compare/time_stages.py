import sys,os,time
sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
from PIL import Image
import torch
img_path='bench_final/FR_paris_0.jpg'
pil=Image.open(img_path).convert('RGB')
from app.geokb import local_engine as le
t0=time.time(); model,proc,tf=le._load_engine(); t_load=time.time()-t0
inp=proc(images=pil,return_tensors='pt')
# 编码一次
t0=time.time()
with torch.no_grad(): feat=model.get_image_features(**inp)
t_enc=time.time()-t0
# 国家打分(复用)
t0=time.time()
with torch.no_grad(): sims=(feat @ tf.T)
t_nat=time.time()-t0
# 复核国家(复用特征, 只是不同prompt文本→但文本已缓存, 只需点积)
t0=time.time()
with torch.no_grad(): _=feat @ tf.T
t_recheck=time.time()-t0
# 城市打分(复用特征)
t0=time.time()
with torch.no_grad(): _=feat @ tf.T
t_city=time.time()-t0
# 不复用: 重新编码
t0=time.time()
with torch.no_grad(): _=model.get_image_features(**inp)
t_reenc=time.time()-t0
print('=== StreetCLIP 单图耗时(CPU) ===')
print(f'加载(一次性): {t_load:.1f}s')
print(f'图像编码一次: {t_enc*1000:.0f}ms')
print(f'国家打分(复用): {t_nat*1000:.2f}ms')
print(f'复核打分(复用): {t_recheck*1000:.2f}ms')
print(f'城市打分(复用): {t_city*1000:.2f}ms')
print(f'重新编码(不复用): {t_reenc*1000:.0f}ms')
print()
print(f'【三级全用StreetCLIP, 编码1次+3次点积】: {t_enc*1000 + (t_nat+t_recheck+t_city)*1000:.0f}ms')
print(f'【三级各编码(不复用)】: {(t_enc+t_reenc*2)*1000 + (t_nat+t_recheck+t_city)*1000:.0f}ms')
