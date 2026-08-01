#!/usr/bin/env python3
from __future__ import annotations
import subprocess, sys
LAYERS=[("unit",["tests/unit","-m","unit and not serial and not live and not pty","-n","2","--dist","loadscope"]),("integration",["tests/integration","-m","integration and not serial and not live and not pty","-n","2","--dist","loadscope"]),("contract",["tests/contract","-m","contract and not serial and not live and not pty","-n","2","--dist","loadscope"]),("serial",["tests","-m","serial and not live and not pty","-n","0"]),("regression",["tests","-m","not unit and not integration and not contract and not system and not serial and not live and not pty","-n","2","--dist","loadscope"])]
COMMON=["-q","--timeout=180","--tb=line"]
def main():
    failed=[]
    for name,args in LAYERS:
        cmd=[sys.executable,"-m","pytest",*args,*COMMON]
        print(f"\n=== layer: {name} ===",flush=True)
        r=subprocess.run(cmd,check=False)
        if r.returncode: failed.append(name)
    if failed: print("Failed:",failed); return 1
    print("All layers passed."); return 0
if __name__=="__main__": raise SystemExit(main())
