#!/usr/bin/env python3
"""Use the installed native Python Tcl interpreter; no Tk window is created."""
from pathlib import Path
import sys
import tkinter

interpreter = tkinter.Tcl()
interpreter.setvar("argv", interpreter.call("list", sys.argv[1]))
try:
    interpreter.call("source", str(Path(__file__).with_name("bt_platform_io_contract.tcl")))
except tkinter.TclError as failure:
    print(str(failure), file=sys.stderr)
    raise SystemExit(1)
