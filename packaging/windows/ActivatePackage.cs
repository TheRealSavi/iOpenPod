// Uses the Windows SDK IApplicationActivationManager ABI (ShObjIdl_core.h).
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace iOpenPodValidation {
    [ComImport, Guid("2e941141-7f97-4756-ba1d-9decde894a3d")]
    [InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    interface IApplicationActivationManager {
        void ActivateApplication(
            [MarshalAs(UnmanagedType.LPWStr)] string appId,
            [MarshalAs(UnmanagedType.LPWStr)] string arguments,
            uint options, out uint processId);
    }

    public static class Launcher {
        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        private static extern IntPtr OpenProcess(
            uint access, [MarshalAs(UnmanagedType.Bool)] bool inheritHandle, uint processId);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool GetExitCodeProcess(IntPtr process, out uint exitCode);

        [DllImport("kernel32.dll", ExactSpelling = true, SetLastError = true)]
        [return: MarshalAs(UnmanagedType.Bool)]
        private static extern bool CloseHandle(IntPtr handle);

        [DllImport("ole32.dll", ExactSpelling = true, PreserveSig = true)]
        private static extern int CoCreateInstance(
            ref Guid classId, IntPtr outer, uint context, ref Guid interfaceId,
            [MarshalAs(UnmanagedType.Interface)] out IApplicationActivationManager manager);

        public static uint? WaitForExit(uint processId, uint milliseconds) {
            if (processId == 0) {
                throw new ArgumentOutOfRangeException("processId");
            }
            // Retain the process object while waiting so its actual termination
            // status remains queryable after exit. Get-Process can lose this.
            const uint queryLimitedInformationAndSynchronize = 0x00101000;
            IntPtr process = OpenProcess(queryLimitedInformationAndSynchronize, false, processId);
            if (process == IntPtr.Zero) {
                int error = Marshal.GetLastWin32Error();
                // A short-lived process can be gone before a handle is opened.
                // The caller must then independently require a fresh PASS report.
                if (error == 87) { return null; } // ERROR_INVALID_PARAMETER
                throw new Win32Exception(error, "Cannot open the launched process.");
            }
            try {
                uint result = WaitForSingleObject(process, milliseconds);
                if (result == 0x00000102) { // WAIT_TIMEOUT
                    throw new TimeoutException("Installed runtime validation timed out; no app processes will be forcibly stopped.");
                }
                if (result == 0xFFFFFFFF) { // WAIT_FAILED
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot wait for the launched process.");
                }
                if (result != 0) { // WAIT_OBJECT_0 is the only valid process completion.
                    throw new InvalidOperationException("Unexpected process wait result: " + result);
                }
                uint exitCode;
                if (!GetExitCodeProcess(process, out exitCode)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error(), "Cannot read the launched process exit code.");
                }
                return exitCode;
            } finally {
                CloseHandle(process);
            }
        }

        public static uint Launch(string appId, string arguments) {
            if (String.IsNullOrWhiteSpace(appId)) {
                throw new ArgumentException("A package application ID is required.", "appId");
            }
            var classId = new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C");
            var interfaceId = new Guid("2e941141-7f97-4756-ba1d-9decde894a3d");
            IApplicationActivationManager manager;
            // CLSCTX_LOCAL_SERVER keeps launch arguments alive independently of
            // this helper's COM reference, as recommended by the Windows SDK.
            Marshal.ThrowExceptionForHR(CoCreateInstance(
                ref classId, IntPtr.Zero, 4, ref interfaceId, out manager));
            try {
                uint processId;
                // AO_NOERRORUI: report activation errors to the script instead
                // of leaving a hidden modal error dialog during validation.
                manager.ActivateApplication(appId, arguments, 2, out processId);
                if (processId == 0) {
                    throw new InvalidOperationException("Activation returned no process ID.");
                }
                return processId;
            } finally {
                Marshal.ReleaseComObject(manager);
            }
        }
    }
}
