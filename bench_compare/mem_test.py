import os, sys, time
def rss_mb():
    # Windows: 用 psutil 或 tracemalloc；跨平台用峰值
    try:
        import psutil
        return psutil.Process().memory_info().rss/1024/1024
    except:
        import ctypes
        class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
            _fields_=[('cb',ctypes.c_uint32),('PageFaultCount',ctypes.c_uint32),
                      ('PeakWorkingSetSize',ctypes.c_size_t),('WorkingSetSize',ctypes.c_size_t),
                      ('QuotaPeakPagedPoolUsage',ctypes.c_size_t),('QuotaPagedPoolUsage',ctypes.c_size_t),
                      ('QuotaPeakNonPagedPoolUsage',ctypes.c_size_t),('QuotaNonPagedPoolUsage',ctypes.c_size_t),
                      ('PagefileUsage',ctypes.c_size_t),('PeakPagefileUsage',ctypes.c_size_t)]
        c=PROCESS_MEMORY_COUNTERS(); c.cb=ctypes.sizeof(c)
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),ctypes.byref(c),c.cb)
        return c.WorkingSetSize/1024/1024

model=sys.argv[1]
base=rss_mb()
if model=='streetclip':
    sys.path.insert(0,os.path.abspath('../street-geolocator-streetclip/backend'))
    from app.geokb import local_engine as le
    le._load_engine()
elif model=='clipH':
    from transformers import CLIPModel,CLIPProcessor
    m=CLIPModel.from_pretrained('laion/CLIP-ViT-H-14-laion2B-s32B-b79K'); m.eval()
elif model=='geoclip':
    import onnxruntime as ort
    s1=ort.InferenceSession('weights/geoclip/vision_model.onnx',providers=['CPUExecutionProvider'])
    s2=ort.InferenceSession('weights/geoclip/location_model.onnx',providers=['CPUExecutionProvider'])
time.sleep(1)
peak=rss_mb()
print(f'{model}: 基线{base:.0f}MB → 加载后{peak:.0f}MB | 模型净增 {peak-base:.0f}MB')
