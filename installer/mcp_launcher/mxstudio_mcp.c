/*
 * mxstudio-mcp.exe - the fixed MCP entry Claude Desktop always starts.
 *
 * It lives in the app home (%LOCALAPPDATA%\ModuleX\MagazineStudio\bin), which survives uninstall,
 * reinstall, moving and upgrading the program. claude_desktop_config.json therefore never changes:
 *     {"command": "<app home>\\bin\\mxstudio-mcp.exe", "args": []}
 * On every start it finds the program through HKCU\Software\ModuleX\MagazineStudio\InstallDir
 * (written by the installer and refreshed by the app), falls back to the default program folder,
 * and runs "<InstallDir>\mxstudio-cli.exe mcp" with ITS OWN stdin/stdout/stderr handles inherited:
 * the JSON-RPC bytes go straight between Claude Desktop and the server, nothing is copied or buffered.
 * A job object kills the server when Claude Desktop ends this launcher. Exit code = the server's.
 *
 * MXS_MCP_TARGET (environment) overrides the target exe; used by tests only.
 * Build (no runtime dependencies, GUI subsystem so no console window ever appears):
 *   x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows -o mxstudio-mcp.exe mxstudio_mcp.c -ladvapi32
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <wchar.h>

#define REG_PATH L"Software\\ModuleX\\MagazineStudio"
#define APP_DIR L"ModuleX Magazine Studio"
#define CLI_EXE L"mxstudio-cli.exe"
#define LAUNCHER_VERSION "1"

static void say(const char *utf8) {
    HANDLE err = GetStdHandle(STD_ERROR_HANDLE);
    DWORD written;
    if (err && err != INVALID_HANDLE_VALUE) WriteFile(err, utf8, (DWORD)lstrlenA(utf8), &written, NULL);
}

static void log_line(const wchar_t *target, DWORD pid, DWORD code, const char *what) {
    wchar_t path[MAX_PATH * 2];
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return;
    lstrcatW(path, L"\\ModuleX\\MagazineStudio\\logs");
    CreateDirectoryW(path, NULL);
    lstrcatW(path, L"\\mcp-launcher.log");
    HANDLE f = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return;
    SYSTEMTIME t;
    GetSystemTime(&t);
    char line[2048];
    char target8[1400] = "";
    if (target) WideCharToMultiByte(CP_UTF8, 0, target, -1, target8, sizeof(target8) - 1, NULL, NULL);
    wsprintfA(line, "%04d-%02d-%02dT%02d:%02d:%02dZ launcher=" LAUNCHER_VERSION " %s pid=%lu code=%lu target=%s\r\n",
              t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond, what, pid, code, target8);
    DWORD written;
    WriteFile(f, line, (DWORD)lstrlenA(line), &written, NULL);
    CloseHandle(f);
}

static int exists(const wchar_t *path) {
    DWORD a = GetFileAttributesW(path);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

static int find_target(wchar_t *out, DWORD cap) {
    DWORD n = GetEnvironmentVariableW(L"MXS_MCP_TARGET", out, cap);
    if (n > 0 && n < cap && exists(out)) return 1;

    wchar_t dir[MAX_PATH * 2];
    DWORD size = sizeof(dir);
    if (RegGetValueW(HKEY_CURRENT_USER, REG_PATH, L"InstallDir", RRF_RT_REG_SZ, NULL, dir, &size) == ERROR_SUCCESS) {
        if (lstrlenW(dir) + 2 + lstrlenW(CLI_EXE) < (int)cap) {
            lstrcpyW(out, dir);
            if (out[lstrlenW(out) - 1] != L'\\') lstrcatW(out, L"\\");
            lstrcatW(out, CLI_EXE);
            if (exists(out)) return 1;
        }
    }
    n = GetEnvironmentVariableW(L"LOCALAPPDATA", dir, MAX_PATH);
    if (n > 0 && n < MAX_PATH) {
        wsprintfW(out, L"%s\\Programs\\%s\\%s", dir, APP_DIR, CLI_EXE);
        if (exists(out)) return 1;
    }
    return 0;
}

static void inheritable(DWORD which) {
    HANDLE h = GetStdHandle(which);
    if (h && h != INVALID_HANDLE_VALUE) SetHandleInformation(h, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR args, int show) {
    (void)inst; (void)prev; (void)args; (void)show;
    wchar_t target[MAX_PATH * 2];
    if (!find_target(target, MAX_PATH * 2)) {
        say("modulex-studio: the Magazine Studio program was not found (HKCU\\Software\\ModuleX\\MagazineStudio"
            "\\InstallDir and the default folder). Reinstall the Studio; Claude Desktop needs no change.\n");
        log_line(NULL, 0, 3, "not-found");
        return 3;
    }
    wchar_t cmd[MAX_PATH * 2 + 16];
    wsprintfW(cmd, L"\"%s\" mcp", target);

    inheritable(STD_INPUT_HANDLE);
    inheritable(STD_OUTPUT_HANDLE);
    inheritable(STD_ERROR_HANDLE);
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);

    HANDLE job = CreateJobObjectW(NULL, NULL);
    if (job) {
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION info;
        ZeroMemory(&info, sizeof(info));
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info, sizeof(info));
    }
    if (!CreateProcessW(target, cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW | CREATE_SUSPENDED, NULL, NULL, &si, &pi)) {
        DWORD e = GetLastError();
        say("modulex-studio: the Studio's MCP server could not be started.\n");
        log_line(target, 0, e, "start-failed");
        return 4;
    }
    if (job) AssignProcessToJobObject(job, pi.hProcess);
    ResumeThread(pi.hThread);
    CloseHandle(pi.hThread);
    log_line(target, pi.dwProcessId, 0, "started");
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    log_line(target, pi.dwProcessId, code, "ended");
    if (job) CloseHandle(job);
    return (int)code;
}
