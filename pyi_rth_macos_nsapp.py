"""PyInstaller runtime hook: initialise Cocoa *before* Qt is loaded.

On macOS 15+ (and especially macOS 26 Tahoe), Qt's C++ static
initializers in QtCore.abi3.so call CFBundleCopyBundleURL(
CFBundleGetMainBundle()) during dlopen.  If the Cocoa application
object hasn't been created yet the bundle's internal _CFInfo pointer
is NULL and the process crashes with EXC_BAD_ACCESS (SIGSEGV).

Calling [NSApplication sharedApplication] via the ObjC runtime
ensures the bundle is fully initialised before any Qt library is
opened.  This hook is listed *before* pyi_rth_pyqt6 in the spec so
it runs first.
"""
import sys

if sys.platform == "darwin":
    import ctypes
    import ctypes.util

    objc_path = ctypes.util.find_library("objc")
    if objc_path:
        objc = ctypes.cdll.LoadLibrary(objc_path)
        objc.objc_getClass.restype = ctypes.c_void_p
        objc.objc_getClass.argtypes = [ctypes.c_char_p]
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = [ctypes.c_char_p]
        objc.objc_msgSend.restype = ctypes.c_void_p
        objc.objc_msgSend.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

        NSApp = objc.objc_getClass(b"NSApplication")
        sel = objc.sel_registerName(b"sharedApplication")
        if NSApp:
            objc.objc_msgSend(NSApp, sel)
