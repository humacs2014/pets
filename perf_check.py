"""资源基准实测脚本（desktop-pet-packaging skill 阶段6-11 资源门）
用法: python perf_check.py <EXE路径> [采样秒数]
流程: 启动EXE → 每2s采样CPU%(累计处理器秒差分,精确) / 内存(WorkingSet64)
判定门: CPU均值≤10% 且 内存峰值≤350MB 才 PASS（基准=v71 实测 6.3%/259MB）。
"""
import subprocess, time, sys, statistics

CPU_AVG_LIMIT = 10.0    # %
MEM_MAX_LIMIT = 350.0   # MB

EXE = sys.argv[1] if len(sys.argv) > 1 else r"dist\宠物.exe"
SAMPLE_S = int(sys.argv[2]) if len(sys.argv) > 2 else 70
DT = 2.0

def ps_sample(pid):
    out = subprocess.check_output(
        ['powershell', '-NoProfile', '-Command',
         f'$p=Get-Process -Id {pid}; "$($p.CPU) $($p.WorkingSet64)"'],
        timeout=15).decode().split()
    return float(out[0]), float(out[1])

proc = subprocess.Popen(EXE)
print('pid', proc.pid, 'waiting 8s startup...')
time.sleep(8)
try:
    prev_cpu, _ = ps_sample(proc.pid)
except Exception as e:
    print('PROC_GONE', e); sys.exit(1)
t0 = time.time()
last_cpu, last_t = prev_cpu, time.time()
cpus, mems, spikes = [], [], []
while time.time() - t0 < SAMPLE_S:
    time.sleep(DT)
    if proc.poll() is not None:
        print('PROC_EXITED during sample', proc.returncode); break
    try:
        cpu_s, ws = ps_sample(proc.pid)
    except Exception:
        continue
    now = time.time()
    pct = max(0.0, (cpu_s - last_cpu) / (now - last_t) * 100.0)
    last_cpu, last_t = cpu_s, now
    cpus.append(pct); mems.append(ws / 1e6)
    if pct > 10: spikes.append(round(pct, 1))

print('samples', len(cpus))
cpu_avg, cpu_med = statistics.mean(cpus), statistics.median(cpus)
cpu_p90, cpu_max = sorted(cpus)[int(len(cpus)*0.9)], max(cpus)
mem_avg, mem_max = statistics.mean(mems), max(mems)
print('CPU avg %.1f%%  median %.1f%%  p90 %.1f%%  max %.1f%%' % (cpu_avg, cpu_med, cpu_p90, cpu_max))
print('MEM avg %.0f MB  max %.0f MB' % (mem_avg, mem_max))
print('CPU spikes >10%%:', spikes if spikes else 'none')
proc.terminate()
try: proc.wait(10)
except subprocess.TimeoutExpired: proc.kill()

ok = cpu_avg <= CPU_AVG_LIMIT and mem_max <= MEM_MAX_LIMIT
print(('PASS' if ok else 'FAIL') + ': CPU avg %.1f%% (limit %.0f%%), MEM max %.0fMB (limit %.0fMB)'
      % (cpu_avg, CPU_AVG_LIMIT, mem_max, MEM_MAX_LIMIT))
sys.exit(0 if ok else 1)
