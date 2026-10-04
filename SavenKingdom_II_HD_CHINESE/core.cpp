// core.cpp — 签名搜索、跳板构造、日志
#include "pch.h"
#include "core.h"
#include <cstdarg>

namespace sk2 {

// -- 日志 -----------------------------------------------------
static HANDLE g_log = nullptr;
static char   g_logPath[MAX_PATH] = {};

void InitLog() {
    if (g_log) return;
    char dir[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, dir, MAX_PATH);
    char* slash = strrchr(dir, '\\');
    if (slash) slash[1] = 0; else dir[0] = 0;

    // 优先写到 update\ 下（资源目录，便于集中管理）；不存在则退回游戏根目录。
    // 顺序：update\ > scripts\ > 游戏根
    static const char* kSubDirs[] = { "update\\", "scripts\\", "" };
    for (const char* sub : kSubDirs) {
        char probe[MAX_PATH] = {};
        lstrcpynA(probe, dir, MAX_PATH);
        lstrcatA(probe, sub);
        DWORD attr = GetFileAttributesA(probe);
        if (sub[0] == 0 || (attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY))) {
            lstrcatA(probe, "sk2_zh.log");
            g_log = CreateFileA(probe, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
            if (g_log != INVALID_HANDLE_VALUE) {
                lstrcpynA(g_logPath, probe, MAX_PATH);
                return;
            }
        }
    }
    // 全部失败则写 TEMP
    char tmp[MAX_PATH] = {};
    GetTempPathA(MAX_PATH, tmp);
    lstrcatA(tmp, "sk2_zh.log");
    lstrcpynA(g_logPath, tmp, MAX_PATH);
    g_log = CreateFileA(tmp, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
}

const char* LogPath() { return g_logPath; }

void LogRaw(const char* buf, int len) {
    if (!g_log || len <= 0) return;
    DWORD written = 0;
    WriteFile(g_log, buf, (DWORD)len, &written, nullptr);
}

void Log(const char* fmt, ...) {
    if (!g_log) return;
    char buf[2048];
    va_list ap;
    va_start(ap, fmt);
    int n = _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    DWORD written = 0;
    WriteFile(g_log, buf, (DWORD)n, &written, nullptr);
}

void CloseLog() {
    if (g_log) { CloseHandle(g_log); g_log = nullptr; }
}

void LogBytes(const char* tag, const void* p, int n) {
    if (!g_log) return;
    char line[512];
    int off = _snprintf_s(line, sizeof(line), _TRUNCATE, "%s:", tag);
    const uint8_t* b = static_cast<const uint8_t*>(p);
    for (int i = 0; i < n && off < (int)sizeof(line) - 4; ++i)
        off += _snprintf_s(line + off, sizeof(line) - off, _TRUNCATE, " %02X", b[i]);
    off += _snprintf_s(line + off, sizeof(line) - off, _TRUNCATE, "\r\n");
    DWORD written = 0;
    WriteFile(g_log, line, (DWORD)off, &written, nullptr);
}

// -- 签名搜索 -------------------------------------------------

// PE 段表解析
struct SegInfo { uint8_t* va; uint32_t vsize; uint32_t rawSize; };

static bool GetTextSegment(SegInfo& out) {
    uint8_t* p = Base();
    if (!p) return false;
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(p);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return false;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS32*>(p + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return false;
    auto* sec = IMAGE_FIRST_SECTION(nt);
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (memcmp(sec->Name, ".text", 5) == 0) {
            out.va     = p + sec->VirtualAddress;
            out.vsize  = sec->Misc.VirtualSize;
            out.rawSize = sec->SizeOfRawData;
            return true;
        }
    }
    return false;
}

void* FindInText(const uint8_t* sig, int sigLen) {
    SegInfo s{};
    if (!GetTextSegment(s)) return nullptr;
    size_t span = s.vsize < s.rawSize ? s.vsize : s.rawSize;
    // 逐字节搜索；.text 约 2.4MB，首次运行一次性开销可接受
    for (size_t i = 0; i + sigLen <= span; ++i) {
        if (memcmp(s.va + i, sig, sigLen) == 0)
            return s.va + i;
    }
    return nullptr;
}

void* FindSignature(void* start, size_t size, const uint8_t* sig, int sigLen) {
    uint8_t* p = static_cast<uint8_t*>(start);
    for (size_t i = 0; i + sigLen <= size; ++i)
        if (memcmp(p + i, sig, sigLen) == 0) return p + i;
    return nullptr;
}

// -- 跳板 -----------------------------------------------------

bool InstallJump(void* target, void* hook, uint8_t* savedBytes) {
    uint8_t* t = static_cast<uint8_t*>(target);
    if (t[0] == 0xE9) {
        Log("[!] target already patched (E9): %p\r\n", target);
        return false;
    }
    if (savedBytes) memcpy(savedBytes, t, 5);

    DWORD old = 0;
    if (!VirtualProtect(t, 5, PAGE_EXECUTE_READWRITE, &old)) {
        Log("[!] VirtualProtect failed at %p (err %lu)\r\n", t, GetLastError());
        return false;
    }
    t[0] = 0xE9;                                   // JMP rel32
    intptr_t dst = reinterpret_cast<intptr_t>(hook);
    intptr_t src = reinterpret_cast<intptr_t>(t) + 5;
    int32_t rel = static_cast<int32_t>(dst - src);
    memcpy(t + 1, &rel, 4);
    FlushInstructionCache(GetCurrentProcess(), t, 5);
    VirtualProtect(t, 5, old, &old);
    return true;
}

void* BuildTrampoline(void* target, size_t stealSize) {
    // 把 target 处「完整指令边界内」的前 stealSize 字节原样复制到一块新内存，
    // 末尾追加 JMP 回 target+stealSize，使调用方能执行「原函数开头」再继续。
    //
    // ★ 关键（曾导致崩溃）：跳板内存必须**永久可执行**。
    //   早期版本把跳板放在 DLL 的静态数组（.data 段，保护 = PAGE_READWRITE），
    //   写完后又 VirtualProtect 恢复成 old（= PAGE_READWRITE），
    //   结果执行跳板时直接 ACCESS_VIOLATION，param[0]=8（EXECUTE）。
    //   对比 InstallJump 之所以没问题：它恢复的是被挂钩函数的原始保护
    //   PAGE_EXECUTE_READ，本来就可执行。
    //   这里改用 VirtualAlloc(PAGE_EXECUTE_READWRITE) 并**不恢复**。
    //
    // stealSize 必须是完整指令个数（如 "55 8B EC 83 EC 20" = 6 字节），
    // 否则会把指令切断。

    const size_t total = stealSize + 16;
    uint8_t* out = static_cast<uint8_t*>(
        VirtualAlloc(nullptr, total, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE));
    if (!out) {
        Log("[!] BuildTrampoline: VirtualAlloc 失败 (err %lu)\r\n", GetLastError());
        return nullptr;
    }

    memcpy(out, target, stealSize);

    // 追加 JMP 回 target+stealSize
    uint8_t* j = out + stealSize;
    j[0] = 0xE9;
    intptr_t back = reinterpret_cast<intptr_t>(target) + static_cast<intptr_t>(stealSize);
    int32_t rel = static_cast<int32_t>(back - reinterpret_cast<intptr_t>(j + 5));
    memcpy(j + 1, &rel, 4);

    FlushInstructionCache(GetCurrentProcess(), out, stealSize + 5);
    // 注意：不调用 VirtualProtect 恢复，保持可执行
    return out;
}

}  // namespace sk2
