#!/usr/bin/env python3
from __future__ import annotations
import argparse, os, re, signal, subprocess, sys, time
from pathlib import Path
_P=(re.compile(r"\[\d+/\d+\]"),re.compile(r"Working\.\.\.",re.I),re.compile(r"chunks:\s*\d+",re.I),re.compile(r"Eval suite complete",re.I),re.compile(r"Build in progress",re.I),re.compile(r"pytest.*passed",re.I))
def _log(m,log_path=None):
    line=f"[watchdog {time.strftime('%H:%M:%S')}] {m}"; print(line,flush=True)
    log_path and open(log_path,"a",encoding="utf-8").write(line+"\n")
def _prog(t): return any(p.search(t) for p in _P)
def _kill(pid):
    if pid<=0: return
    try:
        subprocess.run(["taskkill","/PID",str(pid),"/T","/F"],check=False,capture_output=True) if sys.platform=="win32" else os.killpg(os.getpgid(pid),signal.SIGTERM)
    except Exception: pass
def _watch(log_path,pid,stall,poll,wdlog):
    last=-1; prog=time.monotonic(); log_path.parent.mkdir(parents=True,exist_ok=True); log_path.exists() or log_path.touch()
    while True:
        try: alive=str(pid) in subprocess.run(["tasklist","/FI",f"PID eq {pid}"],capture_output=True,text=True,check=False).stdout
        except Exception: alive=False
        if not alive: _log(f"process {pid} exited",wdlog); return False
        try: size=log_path.stat().st_size
        except OSError: size=0
        if size!=last:
            try: chunk=log_path.read_text(encoding="utf-8",errors="replace")[-8000:]
            except OSError: chunk=""
            if _prog(chunk) or size>last: prog=time.monotonic()
            last=size
        if time.monotonic()-prog>=stall: _log(f"STALL {stall:.0f}s kill {pid}",wdlog); _kill(pid); return True
        time.sleep(poll)
def cmd_run(a):
    if not a.command: print("missing command",file=sys.stderr); return 2
    lp,wl=Path(a.log),Path(a.watchdog_log) if a.watchdog_log else None; lp.parent.mkdir(parents=True,exist_ok=True); r=0
    while True:
        _log("starting: "+ " ".join(a.command),wl)
        with open(lp,"a",encoding="utf-8") as f:
            f.write(f"\n--- watchdog {time.strftime('%F %T')} attempt {r+1} ---\n")
            p=subprocess.Popen(a.command,stdout=f,stderr=subprocess.STDOUT,cwd=a.cwd or None)
        st=_watch(lp,p.pid,a.stall_seconds,a.poll_seconds,wl); p.wait()
        if p.returncode==0: _log("OK",wl); return 0
        if st and r<a.max_restarts: r+=1; _log(f"restart {r}/{a.max_restarts}",wl); time.sleep(a.restart_delay); continue
        _log(f"exit {p.returncode}",wl); return p.returncode or 1
def cmd_daemon(a):
    pf,lp,wl=Path(a.pid_file),Path(a.log),Path(a.watchdog_log) if a.watchdog_log else None; _log("daemon started",wl)
    while True:
        if pf.is_file():
            try: pid=int(pf.read_text(encoding="utf-8").strip())
            except Exception: pid=0
            if pid>0 and _watch(lp,pid,a.stall_seconds,a.poll_seconds,wl) and a.kill_only: pf.unlink(missing_ok=True); return 1
        time.sleep(a.poll_seconds)
def main():
    p=argparse.ArgumentParser(); s=p.add_subparsers(dest="cmd",required=True)
    c=argparse.ArgumentParser(add_help=False); c.add_argument("--log",default="evals/results/watchdog-target.log"); c.add_argument("--watchdog-log",default="evals/results/watchdog.log"); c.add_argument("--stall-seconds",type=float,default=900.0); c.add_argument("--poll-seconds",type=float,default=30.0)
    r=s.add_parser("run",parents=[c]); r.add_argument("--cwd",default="."); r.add_argument("--max-restarts",type=int,default=1); r.add_argument("--restart-delay",type=float,default=5.0); r.add_argument("command",nargs=argparse.REMAINDER); r.set_defaults(func=cmd_run)
    d=s.add_parser("daemon",parents=[c]); d.add_argument("--pid-file",default="evals/results/.watchdog.pid"); d.add_argument("--kill-only",action="store_true"); d.set_defaults(func=cmd_daemon)
    a=p.parse_args();
    if a.cmd=="run" and a.command and a.command[0]=="--": a.command=a.command[1:]
    return a.func(a)
if __name__=="__main__": raise SystemExit(main())
