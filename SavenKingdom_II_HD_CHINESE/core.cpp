// core.cpp — 签名搜索、跳板构造、日志
#include "pch.h"
#include "core.h"
#include <cstdarg>

namespace sk2 {

// -- 日志 -----------------------------------------------------
static HANDLE g_log = nullptr;
static char   g_logPath[MAX_PATH] = {};

// 日志写入也要计时：WriteFile 是同步 IO，落在渲染线程上就是「点一下卡一下」。
// 声明放在此处而不是 include cjk.h，避免 core 依赖渲染模块的头。
void PerfBegin(int id);
void PerfEnd(int id);
static const int PERF_LOG = 9;      // 与 cjk.h 的 PERF_LOG 保持一致
static long g_logWrites = 0;
static long long g_logBytes = 0;
struct LogGuard {
    LogGuard() { PerfBegin(PERF_LOG); }
    ~LogGuard() { PerfEnd(PERF_LOG); }
};
long LogWriteCount() { return g_logWrites; }
long long LogByteCount() { return g_logBytes; }

// ══════════════════════════════════════════════════════════════
// 日志限流 / 熔断 —— 防止 asi 把整个系统拖死
// ══════════════════════════════════════════════════════════════
// 事故模型（用户实测）：游戏一旦卡死，日志是同步 WriteFile 直写磁盘。
// 如果此时我们的 hook 被高频调用（死循环重绘），日志就会以「每秒上千行」
// 的速度砸向磁盘 —— 磁盘 IO 打满，整个操作系统随即无响应。
// 所以日志必须有两道闸：
//   ① 速率闸：每秒最多 MAX_PER_SEC 行，超出的直接丢弃（只计数）；
//   ② 总量闸：累计超过 MAX_BYTES 就彻底静音。日志是诊断工具，
//      绝不允许它成为系统宕机的放大器。
#define LOG_MAX_BYTES   (8LL * 1024 * 1024)
#define LOG_MAX_PER_SEC 200

static volatile LONG g_logMuted = 0;     // 1 = 永久静音（已达总量上限）
static LONG          g_logRateWin = 0;   // 本秒已写行数
static DWORD         g_logRateTick = 0;
static long          g_logDropped = 0;
volatile LONG        g_logMutedFlag = 0; // 供外部（看门狗）查询
long LogDroppedCount() { return g_logDropped; }
int  LogIsMuted() { return g_logMuted; }

static bool LogGate(int len) {
    if (g_logMuted) return false;
    if (g_logBytes + len > LOG_MAX_BYTES) {
        g_logMuted = 1;
        g_logMutedFlag = 1;
        ++g_logDropped;
        return false;
    }
    const DWORD now = GetTickCount();
    if (now - g_logRateTick >= 1000) { g_logRateTick = now; g_logRateWin = 0; }
    if (++g_logRateWin > LOG_MAX_PER_SEC) { ++g_logDropped; return false; }
    return true;
}

// 熔断后的收尾：写一条「已静音」说明（绕过闸门，只此一次），然后关门。
void LogEmergencyStop(const char* why) {
    if (g_log) {
        char b[256];
        int n = _snprintf_s(b, sizeof(b), _TRUNCATE,
                            "\r\n[!] 日志已熔断（%s）：累计 %lld KB / 丢弃 %ld 行。"
                            "后续不再写盘，游戏逻辑不受影响。\r\n",
                            why ? why : "?", g_logBytes / 1024, g_logDropped);
        if (n > 0) { DWORD w = 0; WriteFile(g_log, b, (DWORD)n, &w, nullptr); g_logBytes += w; }
    }
    g_logMuted = 1;
    g_logMutedFlag = 1;
}

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
            // CREATE_ALWAYS：每次进程启动截断旧日志，避免多次运行数据混在一起看不清。
            // 写盘仍用 WriteFile 直落盘（见 LogRaw/Log），进程被杀不丢已写内容。
            g_log = CreateFileA(probe, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
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
    g_log = CreateFileA(tmp, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        nullptr, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
}

const char* LogPath() { return g_logPath; }

void LogRaw(const char* buf, int len) {
    if (!g_log || len <= 0) return;
    if (!LogGate(len)) return;
    LogGuard lg;
    DWORD written = 0;
    WriteFile(g_log, buf, (DWORD)len, &written, nullptr);
    ++g_logWrites; g_logBytes += written;
}

void Log(const char* fmt, ...) {
    if (!g_log) return;
    if (g_logMuted) return;              // 静音后连格式化都省掉
    char buf[2048];
    va_list ap;
    va_start(ap, fmt);
    int n = _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, ap);
    va_end(ap);
    if (n <= 0) return;
    if (!LogGate(n)) return;
    LogGuard lg;
    DWORD written = 0;
    WriteFile(g_log, buf, (DWORD)n, &written, nullptr);
    ++g_logWrites; g_logBytes += written;
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

// -- 通配符签名 -----------------------------------------------

// 把一个十六进制文本模式解析成并行的 pattern/mask 数组。
//   "55 8B ? ? 83 EC"  → pat = {55,8B,00,00,83,EC}
//                        msk = {FF,FF,00,00,FF,FF}
// 约定：mask[i]=0xFF → 必须相等；mask[i]=0x00 → 通配。
// 数字既可以写成两位（"8B"）也可以写一位（"8"），空格可有可无。
//
// 为什么必须支持通配：函数体里含相对调用位移（E8 xx xx xx xx）、
// 栈帧偏移、以及随构建版本变化的绝对立即数；任何写死的字节都会让
// 另一版本搜不到。通配掉这些字节，签名才能跨构建复用。
static int ParseHexPat(const char* s, uint8_t* pat, uint8_t* msk, int cap) {
    int n = 0;
    int hi = -1;                 // 已读到的半字节，-1 表示还没有
    for (const char* q = s; ; ++q) {
        const char c = *q;
        if (c == '?' || c == '*') {
            if (hi >= 0) return -1;        // "8?" 这种半字节通配不接受
            if (n >= cap) return -1;
            pat[n] = 0x00; msk[n] = 0x00; ++n;
            while (*(q + 1) == '?') ++q;   // "??" 也当一个字节
            continue;
        }
        int v = -1;
        if (c >= '0' && c <= '9') v = c - '0';
        else if (c >= 'A' && c <= 'F') v = c - 'A' + 10;
        else if (c >= 'a' && c <= 'f') v = c - 'a' + 10;
        else if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
            if (hi >= 0) {                 // 单位数如 "8" → 0x08
                if (n >= cap) return -1;
                pat[n] = (uint8_t)hi; msk[n] = 0xFF; ++n; hi = -1;
            }
            continue;
        } else if (c == '\0') {
            if (hi >= 0) {
                if (n >= cap) return -1;
                pat[n] = (uint8_t)hi; msk[n] = 0xFF; ++n;
            }
            break;
        } else {
            return -1;                     // 非法字符
        }
        if (hi < 0) {
            hi = v;
        } else {
            if (n >= cap) return -1;
            pat[n] = (uint8_t)((hi << 4) | v); msk[n] = 0xFF; ++n;
            hi = -1;
        }
    }
    return n;
}

// 带通配的线性搜索。.text 约 2.4MB；定位阶段只跑一次，
// 且每个签名平均在前 1MB 内命中，总耗时是毫秒级。
void* FindSignaturePat(void* start, size_t size, const char* hexPat) {
    uint8_t pat[256], msk[256];
    const int n = ParseHexPat(hexPat, pat, msk, 256);
    if (n <= 0) {
        Log("[X] 签名解析失败：%s\r\n", hexPat);
        return nullptr;
    }
    uint8_t* p = static_cast<uint8_t*>(start);
    for (size_t i = 0; i + (size_t)n <= size; ++i) {
        int k = 0;
        for (; k < n; ++k) {
            if (msk[k] && p[i + k] != pat[k]) break;
        }
        if (k == n) return p + i;
    }
    return nullptr;
}

void* FindInTextPat(const char* hexPat) {
    SegInfo s{};
    if (!GetTextSegment(s)) return nullptr;
    size_t span = s.vsize < s.rawSize ? s.vsize : s.rawSize;
    return FindSignaturePat(s.va, span, hexPat);
}

// -- 全映像搜索（字符串块等在 .rdata，不在 .text）─────────────

// PE 段表遍历，只访问「文件里有实数据」的那部分。
// 为什么要 rawSize 与 vsize 取小：bss 式尾部只存在于内存、不来自文件，
// 里面的内容不可预期，纳入搜索只会浪费时间和制造误命中。
void* FindInImagePat(const char* hexPat) {
    uint8_t* p = Base();
    if (!p) return nullptr;
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(p);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return nullptr;
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS32*>(p + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return nullptr;
    auto* sec = IMAGE_FIRST_SECTION(nt);
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        uint32_t span = sec->Misc.VirtualSize < sec->SizeOfRawData
                            ? sec->Misc.VirtualSize : sec->SizeOfRawData;
        if (span < 4) continue;
        void* hit = FindSignaturePat(p + sec->VirtualAddress, span, hexPat);
        if (hit) return hit;
    }
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

// ══════════════════════════════════════════════════════════════
// 定位器
// ══════════════════════════════════════════════════════════════
//
// 每个目标记录：签名 + 命中后的换算 + 兜底 RVA。
// 签名全部在 GOG(7K2.exe) 与 STEAM(7K2_steam.exe) 两个构建上验证过唯一命中，
// 且都通配掉了「相对调用位移 / 栈帧偏移 / 随版本变化的绝对立即数」，
// 因此同一个字符串在两个构建上都能用。
//
// 为什么函数签名不干脆用「全字节精确」：GOG 与 STEAM 是同一份源码的两次
// 构建，函数体里凡涉及被调用函数地址（E8 rel32）、全局地址（imm32）的字节
// 都会变。精确签名只在命中那一版有效 —— 早期就是这么退化成 RVA 的。
namespace {

struct LocEntry {
    LocId       id;
    int         kind;        // loc_kind::*
    const char* pat;         // .text 签名；nullptr = 不用签名（CONST）
    int         delta;       // FUNC: 入口 = match+delta；PTR: 操作数 = match+delta
    int         objSize;     // PTR/CONST: 目标字节数（越界校验用）
    uint32_t    fallbackRva; // 签名未命中时的兜底
};

// ★ 负 delta 的只有 blit8：它的入口序言太通用（n=9），改用循环体内一段
//   唯一特征反推入口。0x5A 是实测的「入口到该特征」字节距离，两版相同。
constexpr int kBlit8Back = -0x5A;

const LocEntry kLocTab[] = {
    // ── 函数入口（kind=FUNC）──────────────────────────────────
    { LOC_TEXT_WIDTH, loc_kind::FUNC,
      "55 8B EC 83 EC 20 89 4D F0 C7 45 F8 00 00 00 00 C7 45 EC 00 00 00 00",
      0, 0, RVA_TEXT_WIDTH },
    { LOC_PUT, loc_kind::FUNC,
      "55 8B EC 83 EC 24 89 4D F4 8B 45 F4 0F BE 08 85 C9 75 08",
      0, 0, RVA_PUT },
    { LOC_PUT_PARAGRAPH, loc_kind::FUNC,
      "55 8B EC 83 EC 30 89 4D F0 8B 45 F0 0F BE 08 85 C9 74",
      0, 0, RVA_PUT_PARAGRAPH },
    { LOC_CENTER_PUT, loc_kind::FUNC,
      "55 8B EC 83 EC 0C 56 89 4D F8 8B 75 10 2B 75 08 83 C6 01 6A 00 6A 00 6A FF",
      0, 0, RVA_CENTER_PUT },
    { LOC_PUT_CHAR, loc_kind::FUNC,
      "55 8B EC 83 EC 08 89 4D FC 0F B7 45 10",
      0, 0, RVA_PUT_CHAR },
    // upper_case / put_ascii / put_ascii2 的栈帧偏移用 ? 通配：
    // 这几条在 STEAM 上局部变量位置有 ±1 字节漂移。
    { LOC_UPPER_CASE, loc_kind::FUNC,
      "55 8B EC 51 89 4D ? 0F BF 45 ? 83 F8 60",
      0, 0, RVA_UPPER_CASE },
    { LOC_PUT_ASCII, loc_kind::FUNC,
      "55 8B EC 83 EC 18 89 4D ? 8B 45 ? 99 2B C2 D1 F8 89 45 ? 8B 45 ? 0F BE 08 85 C9",
      0, 0, RVA_PUT_ASCII },
    { LOC_PUT_ASCII2, loc_kind::FUNC,
      "55 8B EC 83 EC 18 89 4D ? 8B 45 ? 89 45 ? 8B 4D ? 0F BE 11 85 D2",
      0, 0, RVA_PUT_ASCII2 },
    // ★ 这两条单字原语（不挂钩，只直呼）头部几乎相同，必须靠结尾区分：
    //   put_ascii_ch  结尾是 `8B 15 <pal>`（读调色板指针）
    //   put_ascii2_ch 结尾是 `8B E5 5D C2 14 00`（恢复栈帧后 ret 14h）
    //   只用头部会 n=2，把两条混成一条 → 宽度/绘制错位。
    { LOC_PUT_ASCII_CH, loc_kind::FUNC,
      "55 8B EC 83 EC 0C 89 4D FC 0F B7 45 18 8B 4D FC 0F B7 51 15 3B C2 7C ?"
      " 0F B7 45 18 8B 4D FC 0F B7 51 17 3B C2 7F ? 0F B7 45 18 6B C8 07"
      " 8B 55 FC 8B 42 19 03 C1 8B 4D FC 0F B7 51 15 6B CA 07 2B C1 89 45 F8"
      " 8B 55 FC 8B 42 1D 8B 4D F8 03 41 03 89 45 F4 8B 15",
      0, 0, RVA_PUT_ASCII_CH },
    { LOC_PUT_ASCII2_CH, loc_kind::FUNC,
      "55 8B EC 83 EC 0C 89 4D FC 0F B7 45 18 8B 4D FC 0F B7 51 15 3B C2 7C ?"
      " 0F B7 45 18 8B 4D FC 0F B7 51 17 3B C2 7F ? 0F B7 45 18 6B C8 07"
      " 8B 55 FC 8B 42 19 03 C1 8B 4D FC 0F B7 51 15 6B CA 07 2B C1 89 45 F8"
      " 8B 55 FC 8B 42 1D 8B 4D F8 03 41 03 89 45 F4 8B E5 5D C2 14 00",
      0, 0, RVA_PUT_ASCII2_CH },
    { LOC_BLIT8, loc_kind::FUNC,
      "66 8B 04 43 66 89 47 FE 46 E2 EB 03 FA 59 E2 E2",
      kBlit8Back, 0, RVA_BLIT8 },
    // put_bmp 用加长式：短式 n=10。靠穿过 8 个 CC 对齐填充进入 WinMain 序言
    // 才唯一命中。签名尾部保留了这些填充字节，是刻意的。
    { LOC_PUT_BMP, loc_kind::FUNC,
      "55 8B EC 51 89 4D ? A1 ? ? ? ? 50 8B 4D ? 51 8B 55 ? 52 8B 45 ? 50"
      " 8B 4D ? 8B 91 ? ? ? ? 52 8B 45 ? 8B 88 ? ? ? ? 51 E8 ? ? ? ?"
      " 8B E5 5D C2 0C 00 CC CC CC CC CC CC CC CC 55 8D 6C 24 8C",
      0, 0, RVA_PUT_BMP },
    // put_wrap 用入口式签名（SEH 序言，只有它自己匹配）。短式 6 字节
    // `55 8B EC 6A FF 68` 会撞上其他带 SEH 的函数。
    { LOC_PUT_WRAP, loc_kind::FUNC,
      "55 8B EC 6A FF 68 ? ? ? ? 64 A1 00 00 00 00 50 83 EC 38 A1 ? ? ? ? 33 C5"
      " 50 8D 45 F4 64 A3 00 00 00 00 89 4D E0",
      0, 0, RVA_PUT_WRAP },

    // ── 全局变量（kind=PTR：匹配宿主指令，读其中的 imm32 操作数）──
    //
    // 为什么不直接搜立即数：把 `8B 15 E8 CF 69 00`（font_pal）写死，
    // 在 STEAM 上 n=0 —— 立即数就是随版本变的绝对地址，正是必须避开的东西。
    // 改为搜「不含绝对地址的指令上下文」，再读操作数：
    // 运行期读到的立即数已被 loader 修正，天然跟随版本。
    { LOC_G_LINE_COUNT, loc_kind::PTR,
      "83 C4 04 89 45 0C C7 05 ? ? ? ? 01 00 00 00",
      8, 4, RVA_LINE_COUNT },
    { LOC_G_HYPER_ARRAY, loc_kind::PTR,
      "C6 45 FF 00 C6 45 FE 00 C7 45 E4 ? ? ? ?",
      11, 4, RVA_HYPER_ARRAY },
    { LOC_G_HYPER_COUNT, loc_kind::PTR,
      "8B 45 F0 66 89 50 07 33 C9 66 89 0D ? ? ? ?",
      12, 2, RVA_HYPER_COUNT },
    { LOC_G_FONT_PAL, loc_kind::PTR,
      "89 45 F4 8B 15 ? ? ? ? 52 8B 45 F4 50 8B",
      5, 4, RVA_FONT_PAL },
    { LOC_G_USE_BACK, loc_kind::PTR,
      "8A 45 FF A2 ? ? ? ? 8B 4D 08 89 0D ? ? ? ?",
      4, 1, RVA_USE_BACK },
    // OEM 转换表：宿主是 cp437->Latin-1 转换函数（它自己不挂钩）。
    // 表基址两版相同(0x681028)，但同样走「读操作数」以保持形态一致。
    { LOC_G_OEM_TABLE, loc_kind::PTR,
      "0F B6 82 ? ? ? ? 83 F8 3F 74 11",
      3, 4, RVA_OEM_TABLE },

    // ── 只用常量（kind=CONST）────────────────────────────────
    // active_buf：`8B 0D 3C 12 68 00 E8` 在两版各出现 498 次，无法靠指令
    // 特征定位；但它的地址在两版**相同**（0x68123C），且 .rdata 前后偏移
    // 只影响周边变量，所以直接用常量 RVA 是安全且必要的。
    // 记成 CONST 而不是「签名未命中」，避免日志里出现误导性的失败告警。
    { LOC_G_ACTIVE_BUF, loc_kind::FIXEDVA, nullptr, 0, 4, RVA_ACTIVE_BUF },
};

// 字符串块在 .rdata，不在 .text，所以单独用全映像搜索。
// 锚点选这段连续块（Small/PRDY/Large/PRDN…）而不是逐个单词搜：
// "Select"、"Normal" 这类单词在 .rdata 里另有多处，单词搜索必然串味。
const char* const kExeLabelBlockPat =
    "53 6D 61 6C 6C 00 00 00 50 52 44 59 00 00 00 00"
    " 4C 61 72 67 65 00 00 00 50 52 44 4E";

// win_flag / screen_h / screen_w 的宿主：一份被实例化 5 次的模板函数
// （两端各 5 处，地址不同但字节完全相同）。取第一个匹配即可 —— 5 个实例
// 读的是同三个全局。为确保不出错，逐个候选读回并做「尺寸合理性」筛选。
const char* const kClonePat = "55 8B EC 83 EC 14 89 4D EC 0F B6 05";
constexpr int kCloneWinFlag = 0x0C;   // movzx eax, byte_xxxx 的 imm32
constexpr int kCloneScreenH = 0x15;   // mov eax, dword_xxxx
constexpr int kCloneScreenW = 0x3B;   // mov eax, dword_xxxx

uintptr_t ReadImm32(const uint8_t* p) { return *reinterpret_cast<const uint32_t*>(p); }

bool IsReadable(const void* p, size_t n) {
    if (!p || !InImageRange(p, n)) return false;
    MEMORY_BASIC_INFORMATION mbi{};
    if (VirtualQuery(p, &mbi, sizeof(mbi)) == 0) return false;
    if (mbi.State != MEM_COMMIT) return false;
    const DWORD ok = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY
                   | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY;
    return (mbi.Protect & ok) != 0;
}

// 收集同一签名的全部命中（用于克隆函数的候选筛选）。
// 上限 32：只为筛选，不需要完整列表。
int FindAllMatches(const char* pat, void* out[32]) {
    SegInfo s{};
    if (!GetTextSegment(s)) return 0;
    size_t span = s.vsize < s.rawSize ? s.vsize : s.rawSize;
    uint8_t* begin = s.va;
    size_t done = 0;
    int n = 0;
    while (n < 32 && done + 4 < span) {
        void* hit = FindSignaturePat(begin + done, span - done, pat);
        if (!hit) break;
        out[n++] = hit;
        done = static_cast<size_t>(static_cast<uint8_t*>(hit) - begin) + 1;
    }
    return n;
}

}  // namespace

void* g_locAddr[LOC_N] = {};

const char* LocName(LocId id) {
    switch (id) {
        case LOC_TEXT_WIDTH:    return "Font::text_width";
        case LOC_PUT:           return "Font::put";
        case LOC_PUT_PARAGRAPH: return "Font::put_paragraph";
        case LOC_CENTER_PUT:    return "Font::center_put";
        case LOC_PUT_CHAR:      return "Font::put_char";
        case LOC_UPPER_CASE:    return "engine upper_case";
        case LOC_PUT_ASCII:     return "put_ascii";
        case LOC_PUT_ASCII2:    return "put_ascii2";
        case LOC_PUT_ASCII_CH:  return "put_ascii_ch";
        case LOC_PUT_ASCII2_CH: return "put_ascii2_ch";
        case LOC_BLIT8:         return "blit8";
        case LOC_PUT_BMP:       return "put_bmp";
        case LOC_PUT_WRAP:      return "put_wrap";
        case LOC_G_SCREEN_W:    return "g_screen_w";
        case LOC_G_SCREEN_H:    return "g_screen_h";
        case LOC_G_WIN_FLAG:    return "g_win_flag";
        case LOC_G_LINE_COUNT:  return "g_line_count";
        case LOC_G_HYPER_COUNT: return "g_hyper_count";
        case LOC_G_HYPER_ARRAY: return "g_hyper_array";
        case LOC_G_FONT_PAL:    return "g_font_pal";
        case LOC_G_USE_BACK:    return "g_use_back";
        case LOC_G_ACTIVE_BUF:  return "g_active_buf";
        case LOC_G_OEM_TABLE:   return "g_oem_table";
        case LOC_EXE_LABELS:    return "exe_label_block";
        default:                return "?";
    }
}

uint32_t LocVa(LocId id) {
    void* p = g_locAddr[id];
    if (!p) return 0;
    return 0x400000u + static_cast<uint32_t>(
        reinterpret_cast<uint8_t*>(p) - Base());
}

int LocateAll() {
    int hit = 0, miss = 0, konst = 0;

    for (const LocEntry& e : kLocTab) {
        g_locAddr[e.id] = nullptr;

        if (e.kind == loc_kind::FIXEDVA) {
            void* p = Rva(e.fallbackRva);
            g_locAddr[e.id] = IsReadable(p, e.objSize) ? p : nullptr;
            ++konst;
            continue;
        }

        void* m = e.pat ? FindInTextPat(e.pat) : nullptr;
        if (m) {
            uint8_t* cand;
            if (e.kind == loc_kind::FUNC) {
                cand = static_cast<uint8_t*>(m) + e.delta;
                // 函数入口自检：全部目标是标准 prologue。blit8 的 delta 是
                // 负值，也必须落回 `55 8B EC`，这道检查同时验证了 delta。
                if (!(cand[0] == 0x55 && cand[1] == 0x8B && cand[2] == 0xEC))
                    cand = nullptr;
            } else {
                cand = reinterpret_cast<uint8_t*>(
                    static_cast<uintptr_t>(ReadImm32(static_cast<uint8_t*>(m) + e.delta)));
                if (!IsReadable(cand, e.objSize)) cand = nullptr;
            }
            if (cand) {
                g_locAddr[e.id] = cand;
                ++hit;
                continue;
            }
            Log("[!] %s 签名命中 %p 但换算后不可用（delta=%d），转兜底\r\n",
                LocName(e.id), m, e.delta);
        }

        // 兜底：签名未命中 → 退回 RVA。这条路径在 GOG 上等价旧行为，
        // 但必须显式告警，否则「签名悄悄失效」会被误判为「跑得好好的」。
        void* fb = Rva(e.fallbackRva);
        g_locAddr[e.id] = IsReadable(fb, e.objSize) ? fb : nullptr;
        ++miss;
        Log("[F] %s 签名未命中，退回 RVA %08X (%p)\r\n",
            LocName(e.id), e.fallbackRva, g_locAddr[e.id]);
    }

    // ── 克隆函数里的三个全局 ──
    {
        void* cands[32];
        const int nc = FindAllMatches(kClonePat, cands);
        for (int i = 0; i < nc; ++i) {
            uint8_t* base = static_cast<uint8_t*>(cands[i]);
            uint8_t* w = reinterpret_cast<uint8_t*>(
                static_cast<uintptr_t>(ReadImm32(base + kCloneWinFlag)));
            uint8_t* h = reinterpret_cast<uint8_t*>(
                static_cast<uintptr_t>(ReadImm32(base + kCloneScreenH)));
            uint8_t* wd = reinterpret_cast<uint8_t*>(
                static_cast<uintptr_t>(ReadImm32(base + kCloneScreenW)));
            if (!IsReadable(w, 1) || !IsReadable(h, 4) || !IsReadable(wd, 4)) continue;
            const int vw = *reinterpret_cast<const int*>(wd);
            const int vh = *reinterpret_cast<const int*>(h);
            // 尺寸合理性：逻辑画布是 1280x960，接受任何 16..4096 的合理值。
            // 这道筛选让「读到别的变量」不可能被当成成功。
            if (vw <= 16 || vw > 4096 || vh <= 16 || vh > 4096) continue;
            g_locAddr[LOC_G_WIN_FLAG]   = w;
            g_locAddr[LOC_G_SCREEN_H]   = h;
            g_locAddr[LOC_G_SCREEN_W]   = wd;
            ++hit; ++hit; ++hit;
            Log("[O] 克隆宿主 #%d @%08X → screen_w=%d screen_h=%d\r\n",
                i, LocVa(LOC_G_SCREEN_W) - 0x3B, vw, vh);
            break;
        }
        if (!g_locAddr[LOC_G_SCREEN_W]) {
            g_locAddr[LOC_G_SCREEN_W] = Rva(RVA_SCREEN_W);
            g_locAddr[LOC_G_SCREEN_H] = Rva(RVA_SCREEN_H);
            g_locAddr[LOC_G_WIN_FLAG] = Rva(RVA_WINDOW_FLAG);
            miss += 3;
            Log("[F] screen_w/screen_h/win_flag 克隆定位失败，退回 RVA\r\n");
        }
    }

    // ── exe 内置标签块（.rdata）──
    {
        void* blk = FindInImagePat(kExeLabelBlockPat);
        if (blk) {
            g_locAddr[LOC_EXE_LABELS] = blk;
            ++hit;
            Log("[O] exe 标签块 @%08X\r\n", LocVa(LOC_EXE_LABELS));
        } else {
            g_locAddr[LOC_EXE_LABELS] = Rva(RVA_EXE_LABELS);
            ++miss;
            Log("[F] exe 标签块签名未命中，退回 RVA %08X\r\n", RVA_EXE_LABELS);
        }
    }

    Log("[O] 定位完成：签名命中 %d，兜底 %d，常量 %d（共 %d 项）\r\n",
        hit, miss, konst, (int)LOC_N);
    return hit;
}

}  // namespace sk2
