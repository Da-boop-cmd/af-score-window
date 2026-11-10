// af-score 桌面外壳（Win32 + WebView2）
//
// 做的事：
//   1. 选一个空闲端口，拉起随包分发的 python 后端（runtime\python\python.exe -m afscore.web）；
//   2. 等 /api/health 返回 200；
//   3. 用 WebView2 原生窗口加载 http://127.0.0.1:<port>/；
//   4. 关窗时请求 /api/quit 让后端自己退出，超时再强杀。
//
// 构建见 build.bat / build_window.py。

#define UNICODE
#define _UNICODE
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif

#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <wininet.h>
#include <wrl.h>

#include <cstdio>
#include <cstdarg>
#include <string>

#include "WebView2.h"

#pragma comment(lib, "wininet.lib")
#pragma comment(lib, "ws2_32.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "oleaut32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "shell32.lib")
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "advapi32.lib")

using namespace Microsoft::WRL;

static HINSTANCE g_inst = nullptr;
static HWND g_hwnd = nullptr;
static ComPtr<ICoreWebView2Controller> g_ctrl;
static PROCESS_INFORMATION g_child{};
static std::wstring g_root;
static std::wstring g_url;
static int g_port = 0;
static bool g_webview_failed = false;

static void Log(const wchar_t* fmt, ...);

static LONG WINAPI CrashFilter(EXCEPTION_POINTERS* info) {
    Log(L"CRASH code=0x%08lx addr=%p",
        (unsigned long)info->ExceptionRecord->ExceptionCode,
        info->ExceptionRecord->ExceptionAddress);
    return EXCEPTION_EXECUTE_HANDLER;
}

// ------------------------------------------------------------------ 小工具
static std::wstring ModuleDir() {
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD n = GetModuleFileNameW(nullptr, buf, MAX_PATH * 2);
    std::wstring path(buf, n);
    size_t pos = path.find_last_of(L"\\/");
    return pos == std::wstring::npos ? path : path.substr(0, pos);
}

static void Log(const wchar_t* fmt, ...) {
    std::wstring dir = g_root.empty() ? ModuleDir() : g_root;
    std::wstring file = dir + L"\\data\\shell.log";
    CreateDirectoryW((dir + L"\\data").c_str(), nullptr);
    FILE* fp = _wfopen(file.c_str(), L"a, ccs=UTF-8");
    if (!fp) return;
    va_list ap;
    va_start(ap, fmt);
    vfwprintf(fp, fmt, ap);
    va_end(ap);
    fwprintf(fp, L"\n");
    fclose(fp);
}

static int PickFreePort() {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return 8765;
    SOCKET s = socket(AF_INET, SOCK_STREAM, 0);
    int port = 8765;
    if (s != INVALID_SOCKET) {
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        addr.sin_port = 0;
        if (bind(s, (sockaddr*)&addr, sizeof(addr)) == 0) {
            int len = sizeof(addr);
            if (getsockname(s, (sockaddr*)&addr, &len) == 0)
                port = ntohs(addr.sin_port);
        }
        closesocket(s);
    }
    WSACleanup();
    return port;
}

static bool HealthOk() {
    std::wstring url = L"http://127.0.0.1:" + std::to_wstring(g_port) + L"/api/health";
    HINTERNET h = InternetOpenW(L"afscore-shell", INTERNET_OPEN_TYPE_PRECONFIG,
                                nullptr, nullptr, 0);
    if (!h) return false;
    HINTERNET r = InternetOpenUrlW(h, url.c_str(), nullptr, 0,
                                   INTERNET_FLAG_RELOAD | INTERNET_FLAG_NO_CACHE_WRITE, 0);
    bool ok = false;
    if (r) {
        DWORD code = 0, len = sizeof(code);
        if (HttpQueryInfoW(r, HTTP_QUERY_STATUS_CODE | HTTP_QUERY_FLAG_NUMBER,
                           &code, &len, nullptr) && code == 200)
            ok = true;
        InternetCloseHandle(r);
    }
    InternetCloseHandle(h);
    return ok;
}

static void PostQuit() {
    HINTERNET h = InternetOpenW(L"afscore-shell", INTERNET_OPEN_TYPE_PRECONFIG,
                                nullptr, nullptr, 0);
    if (!h) return;
    HINTERNET c = InternetConnectW(h, L"127.0.0.1", (INTERNET_PORT)g_port,
                                   nullptr, nullptr, INTERNET_SERVICE_HTTP, 0, 0);
    if (c) {
        HINTERNET r = HttpOpenRequestW(c, L"POST", L"/api/quit", nullptr, nullptr,
                                       nullptr, INTERNET_FLAG_RELOAD, 0);
        if (r) {
            HttpSendRequestW(r, nullptr, 0, nullptr, 0);
            InternetCloseHandle(r);
        }
        InternetCloseHandle(c);
    }
    InternetCloseHandle(h);
}

// ------------------------------------------------------------------ 后端进程
static bool SpawnBackend() {
    std::wstring py = g_root + L"\\runtime\\python\\python.exe";
    std::wstring cwd = g_root;
    if (GetFileAttributesW(py.c_str()) == INVALID_FILE_ATTRIBUTES) {
        std::wstring venv = g_root + L"\\.venv\\Scripts\\python.exe";  // 开发期回退
        if (GetFileAttributesW(venv.c_str()) != INVALID_FILE_ATTRIBUTES) {
            py = venv;
        } else {
            py = L"python.exe";
        }
    }
    std::wstring data = g_root + L"\\data\\out";
    std::wstring incoming = g_root + L"\\incoming";
    std::wstring predictions = g_root + L"\\data\\predictions";
    std::wstring cmd = L"\"" + py + L"\" -m afscore.web --host 127.0.0.1 --port " +
                       std::to_wstring(g_port) +
                       L" --data \"" + data + L"\" --incoming \"" + incoming + L"\"" +
                       L" --no-open --quiet";
    if (GetFileAttributesW(predictions.c_str()) != INVALID_FILE_ATTRIBUTES)
        cmd += L" --predictions \"" + predictions + L"\"";

    STARTUPINFOW si{};
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    ZeroMemory(&g_child, sizeof(g_child));

    // matplotlib 缓存也放到应用目录，避免写用户配置目录（受限账户/杀软常见报错）
    std::wstring mpl = g_root + L"\\data\\.mpl";
    CreateDirectoryW((g_root + L"\\data").c_str(), nullptr);
    CreateDirectoryW(mpl.c_str(), nullptr);
    SetEnvironmentVariableW(L"MPLCONFIGDIR", mpl.c_str());

    BOOL ok = CreateProcessW(py.c_str(), &cmd[0], nullptr, nullptr, FALSE,
                             CREATE_NO_WINDOW, nullptr, cwd.c_str(), &si, &g_child);
    Log(L"spawn pid=%lu ok=%d cmd=%s", g_child.dwProcessId, (int)ok, cmd.c_str());
    return ok != FALSE;
}

static void StopBackend() {
    if (g_child.hProcess) {
        if (WaitForSingleObject(g_child.hProcess, 1500) == WAIT_TIMEOUT)
            TerminateProcess(g_child.hProcess, 0);
        CloseHandle(g_child.hThread);
        CloseHandle(g_child.hProcess);
    }
    ZeroMemory(&g_child, sizeof(g_child));
}

// ------------------------------------------------------------------ WebView2
static void ResizeWebView() {
    if (!g_ctrl) return;
    RECT rc{};
    GetClientRect(g_hwnd, &rc);
    g_ctrl->put_Bounds(rc);
}

// 兜底：WebView2 起不来时，用 Edge 的应用窗口打开（仍需后端在线）
static bool OpenInEdge() {
    const wchar_t* candidates[] = {
        L"C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
        L"C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    };
    for (const wchar_t* exe : candidates) {
        if (GetFileAttributesW(exe) == INVALID_FILE_ATTRIBUTES) continue;
        std::wstring cmd = std::wstring(L"\"") + exe + L"\" --app=" + g_url +
                           L" --window-size=1456,940";
        STARTUPINFOW si{};
        si.cb = sizeof(si);
        PROCESS_INFORMATION pi{};
        if (CreateProcessW(exe, &cmd[0], nullptr, nullptr, FALSE, 0, nullptr,
                           g_root.c_str(), &si, &pi)) {
            Log(L"fallback edge pid=%lu", pi.dwProcessId);
            WaitForSingleObject(pi.hProcess, INFINITE);
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            return true;
        }
    }
    return false;
}

static void InitWebView() {
    // 用户数据目录必须可写：默认在 %LOCALAPPDATA%，受限账户/漫游配置下会失败，
    // 所以显式放到应用自己的 data 目录里（也便于整包搬走）
    std::wstring udf = g_root + L"\\data\\webview2";
    CreateDirectoryW((g_root + L"\\data").c_str(), nullptr);
    CreateDirectoryW(udf.c_str(), nullptr);

    HRESULT hr = CreateCoreWebView2EnvironmentWithOptions(
        nullptr, udf.c_str(), nullptr,
        Callback<ICoreWebView2CreateCoreWebView2EnvironmentCompletedHandler>(
            [](HRESULT result, ICoreWebView2Environment* env) -> HRESULT {
                if (FAILED(result) || !env) {
                    g_webview_failed = true;
                    Log(L"env failed hr=0x%08lx", (unsigned long)result);
                    PostMessageW(g_hwnd, WM_APP + 1, 0, 0);
                    return result;
                }
                env->CreateCoreWebView2Controller(
                    g_hwnd,
                    Callback<ICoreWebView2CreateCoreWebView2ControllerCompletedHandler>(
                        [](HRESULT r2, ICoreWebView2Controller* ctrl) -> HRESULT {
                            if (FAILED(r2) || !ctrl) {
                                g_webview_failed = true;
                                Log(L"controller failed hr=0x%08lx", (unsigned long)r2);
                                PostMessageW(g_hwnd, WM_APP + 1, 0, 0);
                                return r2;
                            }
                            g_ctrl = ctrl;
                            ResizeWebView();
                            ComPtr<ICoreWebView2> wv;
                            ctrl->get_CoreWebView2(&wv);
                            if (wv) wv->Navigate(g_url.c_str());
                            Log(L"navigate %s", g_url.c_str());
                            return S_OK;
                        }).Get());
                return S_OK;
            }).Get());
    if (FAILED(hr)) {
        g_webview_failed = true;
        Log(L"CreateCoreWebView2EnvironmentWithOptions hr=0x%08lx", (unsigned long)hr);
        PostMessageW(g_hwnd, WM_APP + 1, 0, 0);
    }
}

// ------------------------------------------------------------------ 窗口
static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE:
        Log(L"wm_create");
        return 0;
    case WM_APP + 2:                 // 窗口建好、消息循环跑起来之后再初始化 WebView2
        Log(L"init webview");
        InitWebView();
        return 0;
    case WM_SIZE:
        ResizeWebView();
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    case WM_APP + 1:
        if (!GetEnvironmentVariableW(L"AFSCORE_SHELL_SILENT", nullptr, 0)) {
            MessageBoxW(g_hwnd, L"WebView2 初始化失败，将改用 Edge 窗口打开。",
                        L"af-score", MB_ICONWARNING);
        }
        DestroyWindow(g_hwnd);
        return 0;
    case WM_GETMINMAXINFO: {
        auto* mmi = (MINMAXINFO*)lp;
        mmi->ptMinTrackSize.x = 1200;
        mmi->ptMinTrackSize.y = 760;
        return 0;
    }
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

static bool CreateMainWindow(int nCmdShow) {
    HICON icoBig = (HICON)LoadImageW(g_inst, MAKEINTRESOURCEW(1), IMAGE_ICON, 0, 0,
                                     LR_DEFAULTSIZE | LR_SHARED);
    HICON icoSmall = (HICON)LoadImageW(g_inst, MAKEINTRESOURCEW(1), IMAGE_ICON,
                                       GetSystemMetrics(SM_CXSMICON),
                                       GetSystemMetrics(SM_CYSMICON), LR_SHARED);

    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = g_inst;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hIcon = icoBig ? icoBig : LoadIconW(nullptr, IDI_APPLICATION);
    wc.hIconSm = icoSmall ? icoSmall : LoadIconW(nullptr, IDI_APPLICATION);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = L"AfscoreWindowClass";
    if (!RegisterClassExW(&wc)) return false;

    // 窗口尺寸：优先 1680×1050；屏幕小就用工作区的 92%/90%，并居中
    RECT work{};
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    int availW = work.right - work.left;
    int availH = work.bottom - work.top;
    int w = (availW >= 1750) ? 1680 : int(availW * 0.92);
    int h = (availH >= 1100) ? 1050 : int(availH * 0.90);
    int x = work.left + (availW - w) / 2;
    int y = work.top + (availH - h) / 2;
    g_hwnd = CreateWindowExW(0, wc.lpszClassName, L"AlphaFold3 评分看板 v1.2",
                             WS_OVERLAPPEDWINDOW, x, y, w, h,
                             nullptr, nullptr, g_inst, nullptr);
    if (!g_hwnd) return false;
    if (icoBig) SendMessageW(g_hwnd, WM_SETICON, ICON_BIG, (LPARAM)icoBig);
    if (icoSmall) SendMessageW(g_hwnd, WM_SETICON, ICON_SMALL, (LPARAM)icoSmall);
    ShowWindow(g_hwnd, nCmdShow);
    UpdateWindow(g_hwnd);
    return true;
}

int WINAPI wWinMain(HINSTANCE hInst, HINSTANCE, PWSTR, int nCmdShow) {
    g_inst = hInst;
    g_root = ModuleDir();
    SetUnhandledExceptionFilter(CrashFilter);
    CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);   // WebView2 需要 COM
    SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
    Log(L"winmain root=%s", g_root.c_str());

    SetLastError(0);
    HANDLE mtx = CreateMutexW(nullptr, TRUE, L"afscore-window-singleton");
    DWORD mtxErr = GetLastError();
    Log(L"mutex err=%lu ptr=%p", (unsigned long)mtxErr, mtx);
    if (mtx && mtxErr == ERROR_ALREADY_EXISTS) {
        MessageBoxW(nullptr, L"af-score 已经在运行，请先关闭那个窗口。",
                    L"af-score", MB_ICONINFORMATION);
        return 0;
    }

    g_port = PickFreePort();
    if (!SpawnBackend()) {
        MessageBoxW(nullptr, L"启动后端失败。\n请确认 runtime\\python\\python.exe 存在。",
                    L"af-score", MB_ICONERROR);
        return 1;
    }

    bool ready = false;
    for (int i = 0; i < 240; ++i) {          // 最多等 60 秒
        if (HealthOk()) { ready = true; break; }
        Sleep(250);
    }
    Log(L"health ready=%d port=%d", (int)ready, g_port);
    if (!ready) {
        StopBackend();
        MessageBoxW(nullptr, L"后端启动超时（60 秒）。\n详见 data\\shell.log。",
                    L"af-score", MB_ICONERROR);
        return 1;
    }

    g_url = L"http://127.0.0.1:" + std::to_wstring(g_port) + L"/";
    if (!CreateMainWindow(nCmdShow)) {
        StopBackend();
        return 1;
    }
    PostMessageW(g_hwnd, WM_APP + 2, 0, 0);   // 进消息循环后再建 WebView2

    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    if (g_webview_failed) {
        if (OpenInEdge()) {
            PostQuit();
            Sleep(300);
            StopBackend();
            Log(L"exit (edge fallback)");
            CoUninitialize();
            return 0;
        }
        MessageBoxW(nullptr, L"WebView2 与 Edge 都不可用，无法显示界面。",
                    L"af-score", MB_ICONERROR);
    }

    PostQuit();
    Sleep(400);
    StopBackend();
    Log(L"exit");
    CoUninitialize();
    return 0;
}
