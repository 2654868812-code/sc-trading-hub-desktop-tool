"""独立截图进程 — 截一张图后立即退出，内存随进程归还 OS。

主程序 F3 时 spawn 本进程（FT-Capture.exe / python capture_main.py）。
mss/GDI 截图每帧残留 ~20MB 堆内存不归还，放在短命子进程里解决。
用法: capture_main.py <output.png>
"""
import sys
import mss

def main():
    if len(sys.argv) < 2:
        sys.exit(2)
    with mss.mss() as sct:
        sct.shot(output=sys.argv[1])
    sys.exit(0)


if __name__ == "__main__":
    main()
