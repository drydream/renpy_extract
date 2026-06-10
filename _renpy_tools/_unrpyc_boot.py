import sys, os
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)
sys.argv[0] = os.path.join(_here, "unrpyc.py")
_src = open(sys.argv[0], "rb").read()
exec(compile(_src, sys.argv[0], "exec"))
