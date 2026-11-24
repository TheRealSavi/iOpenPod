/* Storage's one-operation UAC helper. No Python, plugins, firmware or CDBs.
 * Build with a static CRT and system-only dependent DLL search. */
#define WIN32_LEAN_AND_MEAN
#define _WIN32_WINNT 0x0A00
#include <windows.h>
#include <winioctl.h>
#include <stdint.h>
#include <stdlib.h>
#include <wchar.h>

#define MAGIC 0x31504f49UL
#define TIMEOUT_MS 120000UL

typedef struct {
    DWORD magic;
    DWORD error;
    uint64_t handle;
} Reply;

static BOOL volume_name(const wchar_t *s) {
    size_t i;
    if (wcslen(s) != 48 || wcsncmp(s, L"\\\\?\\Volume{", 11) || s[47] != L'}')
        return FALSE;
    for (i = 11; i < 47; ++i) {
        if (i == 19 || i == 24 || i == 29 || i == 34) {
            if (s[i] != L'-') return FALSE;
        } else if (!((s[i] >= L'0' && s[i] <= L'9') ||
                     (s[i] >= L'a' && s[i] <= L'f') ||
                     (s[i] >= L'A' && s[i] <= L'F'))) return FALSE;
    }
    return TRUE;
}

static BOOL pipe_name(const wchar_t *s) {
    const wchar_t *prefix = L"\\\\.\\pipe\\iOpenPod-volume-";
    size_t start = wcslen(prefix), i;
    if (wcslen(s) != start + 32 || wcsncmp(s, prefix, start)) return FALSE;
    for (i = start; i < start + 32; ++i)
        if (!((s[i] >= L'0' && s[i] <= L'9') ||
              (s[i] >= L'a' && s[i] <= L'f'))) return FALSE;
    return TRUE;
}

static BOOL number(const wchar_t *s, uint64_t *value) {
    wchar_t *end;
    if (!*s || *s < L'0' || *s > L'9' || wcslen(s) > 19) return FALSE;
    *value = _wcstoui64(s, &end, 10);
    return !*end;
}

static BOOL transfer(HANDLE pipe, HANDLE parent, void *data, DWORD size, BOOL write) {
    OVERLAPPED operation = {0};
    DWORD count = 0, error, waited;
    HANDLE waits[2];
    BOOL result;
    operation.hEvent = CreateEventW(NULL, TRUE, FALSE, NULL);
    if (!operation.hEvent) return FALSE;
    result = write ? WriteFile(pipe, data, size, &count, &operation)
                   : ReadFile(pipe, data, size, &count, &operation);
    error = result ? ERROR_SUCCESS : GetLastError();
    if (!result && error == ERROR_IO_PENDING) {
        waits[0] = operation.hEvent;
        waits[1] = parent;
        waited = WaitForMultipleObjects(2, waits, FALSE, TIMEOUT_MS);
        if (waited != WAIT_OBJECT_0) {
            CancelIoEx(pipe, &operation);
            GetOverlappedResult(pipe, &operation, &count, TRUE);
            error = ERROR_TIMEOUT;
        } else {
            result = GetOverlappedResult(pipe, &operation, &count, FALSE);
            error = result ? ERROR_SUCCESS : GetLastError();
        }
    }
    CloseHandle(operation.hEvent);
    SetLastError(error);
    return result && count == size;
}

static DWORD open_volume(const wchar_t *name, DWORD disk, HANDLE *volume) {
    STORAGE_DEVICE_NUMBER identity = {0};
    STORAGE_PROPERTY_QUERY query = {StorageDeviceProperty, PropertyStandardQuery, {0}};
    STORAGE_DEVICE_DESCRIPTOR descriptor = {0};
    DWORD count = 0;
    *volume = CreateFileW(name, GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                         OPEN_EXISTING, 0, NULL);
    if (*volume == INVALID_HANDLE_VALUE) return GetLastError();
    if (!DeviceIoControl(*volume, IOCTL_STORAGE_GET_DEVICE_NUMBER, NULL, 0,
                         &identity, sizeof(identity), &count, NULL)) return GetLastError();
    if (count != sizeof(identity) || identity.DeviceType != FILE_DEVICE_DISK ||
        identity.DeviceNumber != disk) return ERROR_DEVICE_NOT_CONNECTED;
    if (!DeviceIoControl(*volume, IOCTL_STORAGE_QUERY_PROPERTY, &query, sizeof(query),
                         &descriptor, sizeof(descriptor), &count, NULL)) return GetLastError();
    if (count < offsetof(STORAGE_DEVICE_DESCRIPTOR, RawDeviceProperties) ||
        descriptor.BusType != BusTypeUsb) return ERROR_NOT_SUPPORTED;
    return ERROR_SUCCESS;
}

int wmain(int argc, wchar_t **argv) {
    HANDLE parent = NULL, pipe = INVALID_HANDLE_VALUE, volume = INVALID_HANDLE_VALUE;
    HANDLE token = NULL, remote = NULL, reclaimed = NULL;
    FILETIME created, exited, kernel, user;
    TOKEN_ELEVATION elevated;
    DWORD peer = 0, count = 0, ready = 0, error = ERROR_INVALID_PARAMETER;
    uint64_t pid, birth, disk;
    Reply reply = {MAGIC, ERROR_SUCCESS, 0};
    BOOL probe = argc == 7 && !wcscmp(argv[1], L"--check-ipc");
    if (probe) { --argc; ++argv; }
    if (argc == 2 && !wcscmp(argv[1], L"--self-test")) {
        return volume_name(L"\\\\?\\Volume{01234567-89ab-cdef-0123-456789abcdef}") &&
               !volume_name(L"\\\\.\\PhysicalDrive0") &&
               pipe_name(L"\\\\.\\pipe\\iOpenPod-volume-0123456789abcdef0123456789abcdef") ? 0 : 1;
    }
    if (argc != 6 || !pipe_name(argv[1]) || !number(argv[2], &pid) ||
        !number(argv[3], &birth) || !volume_name(argv[4]) || !number(argv[5], &disk) ||
        !pid || pid > MAXDWORD || disk > MAXDWORD) goto done;
    parent = OpenProcess(PROCESS_DUP_HANDLE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
                         FALSE, (DWORD)pid);
    if (!parent) { error = GetLastError(); goto done; }
    if (!GetProcessTimes(parent, &created, &exited, &kernel, &user) ||
        (((uint64_t)created.dwHighDateTime << 32) | created.dwLowDateTime) != birth ||
        WaitForSingleObject(parent, 0) != WAIT_TIMEOUT) { error = ERROR_ACCESS_DENIED; goto done; }
    pipe = CreateFileW(argv[1], GENERIC_READ | GENERIC_WRITE, 0, NULL, OPEN_EXISTING,
                      FILE_FLAG_OVERLAPPED | SECURITY_SQOS_PRESENT | SECURITY_IDENTIFICATION, NULL);
    if (pipe == INVALID_HANDLE_VALUE) { error = GetLastError(); goto done; }
    if (!GetNamedPipeServerProcessId(pipe, &peer) || peer != (DWORD)pid) {
        error = ERROR_ACCESS_DENIED; goto done;
    }
    if (!transfer(pipe, parent, &ready, sizeof(ready), FALSE) || ready != MAGIC) {
        error = ERROR_INVALID_DATA; goto done;
    }
    if (probe) reply.error = ERROR_NOT_SUPPORTED;  /* No device/privilege access. */
    else if (!OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &token) ||
        !GetTokenInformation(token, TokenElevation, &elevated, sizeof(elevated), &count))
        reply.error = GetLastError();
    else if (!elevated.TokenIsElevated) reply.error = ERROR_ELEVATION_REQUIRED;
    else reply.error = open_volume(argv[4], (DWORD)disk, &volume);
    if (!reply.error && !DuplicateHandle(GetCurrentProcess(), volume, parent,
                                        &remote, 0, FALSE, DUPLICATE_SAME_ACCESS))
        reply.error = GetLastError();
    if (volume != INVALID_HANDLE_VALUE) { CloseHandle(volume); volume = INVALID_HANDLE_VALUE; }
    reply.handle = (uint64_t)(uintptr_t)remote;
    /* Ownership passes with the one complete message. Never close a published
     * remote handle: the receiving process may already have closed/reused it. */
    if (!transfer(pipe, parent, &reply, sizeof(reply), TRUE)) {
        error = GetLastError();
        if (remote && DuplicateHandle(parent, remote, GetCurrentProcess(), &reclaimed,
                                      0, FALSE, DUPLICATE_CLOSE_SOURCE)) CloseHandle(reclaimed);
        goto done;
    }
    error = ERROR_SUCCESS;
done:
    if (token) CloseHandle(token);
    if (volume != INVALID_HANDLE_VALUE) CloseHandle(volume);
    if (pipe != INVALID_HANDLE_VALUE) CloseHandle(pipe);
    if (parent) CloseHandle(parent);
    return (int)error;
}
