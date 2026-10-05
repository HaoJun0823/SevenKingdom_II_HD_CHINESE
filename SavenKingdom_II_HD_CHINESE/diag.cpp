// diag.cpp — 乱码诊断日志：把「屏幕上那段乱码到底是什么」写到文件里
//
// 判读方式（不需要截图）
// --------------------
//   flags=MISS      字节对本身正确，但字库里没有这个形状 -> 是字库缺口
//   flags=BADTRAIL  lead 之后的第二字节不合法          -> 读取起点错位了
//   flags=ODD       字符串在 lead 处被 NUL 截断        -> 字段被截断，多半是资源写坏
//   flags=CTRL      串里混入引擎控制符                 -> 该重映射的字没重映射
//   stk=...         调用链（IDA VA）                   -> 反查是哪个引擎函数在画
//
// 列举的 uni 行给出每个双字节对查到的字形索引，-1 表示查不到。
#include "pch.h"
#include "core.h"
#include "diag.h"
#include "cjk.h"
#include <windows.h>

namespace sk2 {

// ── Big5 / 自定义对的判定（与 cjk.cpp 的 GlyphIndex 保持一致）──
static inline bool TrailOkU(unsigned char t) {
    return (t >= 0x40 && t <= 0x7E) || (t >= 0xA1 && t <= 0xFE);
}
static inline bool IsLeadU(unsigned char c) {
    return (c >= 0xA1 && c <= 0xF9) || (c >= 0x90 && c <= 0xA0);
}
static inline bool PairU(unsigned char a, unsigned char b) {
    return IsLeadU(a) && TrailOkU(b);
}

static const char kHex[] = "0123456789ABCDEF";

// ── 极简格式化（不碰 CRT 的安全版 printf，避免 hook 里触发进程终止）──
static int AS(char* d, int cap, const char* s) {
    int n = 0;
    while (s[n] && n < cap - 1) { d[n] = s[n]; ++n; }
    return n;
}
static int AH2(char* d, int cap, unsigned v) {
    if (cap < 3) return 0;
    d[0] = kHex[(v >> 4) & 15];
    d[1] = kHex[v & 15];
    return 2;
}
static int AH8(char* d, int cap, unsigned v) {
    if (cap < 9) return 0;
    for (int i = 7; i >= 0; --i) d[7 - i] = kHex[(v >> (4 * i)) & 15];
    return 8;
}
static int AU(char* d, int cap, unsigned v) {
    char t[12];
    int n = 0;
    if (!v) t[n++] = '0';
    while (v && n < 12) { t[n++] = (char)('0' + (v % 10)); v /= 10; }
    int w = 0;
    while (n > 0 && w < cap - 1) d[w++] = t[--n];
    return w;
}
static int AInt(char* d, int cap, int v) {
    if (v < 0) { int n = AS(d, cap, "-"); return n + AU(d + n, cap - n, (unsigned)(-v)); }
    return AU(d, cap, (unsigned)v);
}

// ── 配置 ────────────────────────────────────────────────────
static CRITICAL_SECTION g_cs;
static long             g_seq = 0;
static volatile LONG    g_level = 0;
static bool             g_csReady = false;

// 必须由加载阶段的单线程先调用一次（LoadRenderCfg 里做）。
// 之后 DiagText 才可能在任意 UI 线程里被并发调用。
void DiagInit(int level) {
    if (!g_csReady) { InitializeCriticalSection(&g_cs); g_csReady = true; }
    g_level = level;
}
int  DiagLevel() { return g_level; }

// ── 缺字形统计表 ────────────────────────────────────────────
#define MISS_MAX 256
struct MissEnt { unsigned short code; long count; };
static MissEnt g_miss[MISS_MAX];
static int     g_missN = 0;

static void MissAdd(unsigned short code) {
    for (int i = 0; i < g_missN; ++i)
        if (g_miss[i].code == code) { g_miss[i].count++; return; }
    if (g_missN < MISS_MAX) { g_miss[g_missN].code = code; g_miss[g_missN].count = 1; ++g_missN; }
}

// ── 去重：UI 每帧重绘同样的内容，避免日志爆炸 ────────────────
#define SEEN_MAX 600
static unsigned g_seen[SEEN_MAX];
static int      g_seenN = 0;
static int      g_seenPos = 0;

static bool Dedup(unsigned h) {
    for (int i = 0; i < g_seenN; ++i) if (g_seen[i] == h) return true;
    if (g_seenN < SEEN_MAX) g_seen[g_seenN++] = h;
    else { g_seenPos = (g_seenPos + 1) % SEEN_MAX; g_seen[g_seenPos] = h; }
    return false;
}

static unsigned Fnv(const unsigned char* s, unsigned seed) {
    unsigned h = seed;
    while (*s) { h ^= *s++; h *= 16777619u; }
    return h;
}

// ── 内存可读性（走 EBP 链前必须逐个校验，否则一次误读就崩）──
static bool ReadableC(const void* p, size_t n) {
    MEMORY_BASIC_INFORMATION mbi;
    SIZE_T got = VirtualQuery(p, &mbi, sizeof(mbi));
    if (got != sizeof(mbi)) return false;
    if (mbi.State != MEM_COMMIT) return false;
    if (mbi.Protect & (PAGE_NOACCESS | PAGE_GUARD)) return false;
    return mbi.RegionSize >= n;
}

static int ScrW() {
    const int* p = LocInt(LOC_G_SCREEN_W);   // 定位器给出（签名优先、RVA 兜底）
    const int v = p ? *p : 0;
    return (v > 16 && v <= 4096) ? v : 1280;
}

// ── 把 cp950 字节流转成 UTF-8 写入（逐单元，保证任何字节流都有可读输出）──
void AppendCp950Utf8(char* d, int cap, int* used, const unsigned char* s, int len) {
    if (!ReadableC(s, len)) { *used += AS(d + *used, cap - *used, "(不可读)"); return; }
    int i = 0;
    while (i < len && *used < cap - 12) {
        unsigned char c = s[i];
        if (c < 0x80) {
            if (c >= 0x20 && c < 0x7F) d[(*used)++] = (char)c;
            else if (c == 0x0A) { d[(*used)++] = '\\'; d[(*used)++] = 'n'; }
            else if (c == 0x09) { d[(*used)++] = '\\'; d[(*used)++] = 't'; }
            i++;
            continue;
        }
        if (PairU(c, s[i + 1]) && s[i + 1]) {
            WCHAR w[8];
            int nw = MultiByteToWideChar(950, 0, (const char*)(s + i), 2, w, 8);
            if (nw > 0) {
                int nb = WideCharToMultiByte(CP_UTF8, 0, w, nw, d + *used, cap - *used - 1,
                                             nullptr, nullptr);
                if (nb > 0) { *used += nb; i += 2; d[*used] = 0; continue; }
            }
            int p = *used;
            p += AS(d + p, cap - p, "<");
            p += AH2(d + p, cap - p, c);
            p += AH2(d + p, cap - p, s[i + 1]);
            p += AS(d + p, cap - p, ">");
            *used = p;
            i += 2;
            continue;
        }
        int p = *used;
        p += AS(d + p, cap - p, "<");
        p += AH2(d + p, cap - p, c);
        p += AS(d + p, cap - p, ">");
        *used = p;
        i += 1;
    }
    d[*used] = 0;
}

// ── 调用栈（IDA VA 形式，可直接反查）────────────────────────
// callerFrame 只有在「它的 +4 处正好等于已知 retAddr」时才被信任 —— 这样
// 即使编译器做了 FPO 优化导致 EBP 不是帧指针，也只会跳过回溯而不会打印垃圾。
static void AppendStack(char* d, int cap, int* used, uint32_t frame, uint32_t wantRet) {
    if (!frame) return;
    if (!ReadableC((const void*)frame, 8)) return;
    if (*(const uint32_t*)(frame + 4) != wantRet) return;

    const uint32_t base = reinterpret_cast<uint32_t>(Base());
    for (int i = 0; i < 14 && *used < cap - 12; ++i) {
        if (!ReadableC((const void*)frame, 8)) break;
        const uint32_t ret = *(const uint32_t*)(frame + 4);
        const uint32_t next = *(const uint32_t*)frame;
        if (ret > base && ret < base + 0x0C00000u) {
            if (*used > 0 && i > 0) { d[(*used)++] = '<'; d[(*used)++] = '-'; }
            *used += AH8(d + *used, cap - *used, 0x400000u + (ret - base));
        }
        if (next <= frame) break;
        frame = next;
    }
    d[*used] = 0;
}

// ══════════════════════════════════════════════════════════════
// 主入口
// ══════════════════════════════════════════════════════════════
// 真正的实现。外面套了一层 SEH，见下。
static void DiagTextBody(const char* kind, const void* fontObj, const char* str,
                         int x, int y, int x2, int endX, void* retAddr, uint32_t frame)
{
    if (!str) return;
    const int lv = DiagLevel();
    if (!lv) return;
    if (!ReadableC(str, 1)) return;

    // ── 第一遍：扫描，算出长度、配对情况、flags ───────────────
    int len = 0;
    while (len < 1024 && str[len]) ++len;
    if (len == 0) return;

    unsigned flags = 0;
    int nPairs = 0, nHigh = 0, nCust = 0;
    {
        const unsigned char* p = (const unsigned char*)str;
        while (*p) {
            unsigned char c = *p;
            if (c >= 0x80) ++nHigh;
            if (PairU(c, p[1]) && p[1]) {
                ++nPairs;
                if (c >= 0x90 && c <= 0xA0) ++nCust;
                if (GlyphIndex(c, p[1]) < 0) { flags |= 1u; MissAdd((unsigned short)((c << 8) | p[1])); }
                p += 2;
                continue;
            }
            if (IsLeadU(c)) {
                // lead 之后没有合法 trail —— 要么就是 NUL 截断（ODD），
                // 要么 trail 落在控制符区（BADTRAIL）。两者都是错位信号。
                if (!p[1]) flags |= 16u;
                else if (p[1] < 0x40 || (p[1] >= 0x7F && p[1] <= 0xA0)) flags |= 2u;
            }
            if ((c >= 0x5B && c <= 0x5D) || (c >= 0x7B && c <= 0x7F)) flags |= 4u;
            ++p;
        }
    }
    if (endX >= ScrW()) flags |= 8u;
    if (nCust)          flags |= 32u;

    if (lv < 3 && nHigh == 0) return;         // 纯 ASCII：lv3 才记
    if (lv == 1 && flags == 0) return;        // lv1：只记可疑

    // 去重键：内容 + 字体 + 坐标（同一帧重复绘制会命中）
    unsigned hash = Fnv((const unsigned char*)str, 2166136261u);
    hash ^= (unsigned)(uintptr_t)fontObj * 2654435761u;
    hash ^= (unsigned)x * 40503u + (unsigned)y;
    if (Dedup(hash)) return;

    EnterCriticalSection(&g_cs);
    const int seq = InterlockedIncrement(&g_seq);
    LeaveCriticalSection(&g_cs);

    char buf[4600];
    int n = 0;
    const int cap = sizeof(buf);

    // ── 头一行 ────────────────────────────────────────────────
    n += AS(buf + n, cap - n, "[ZH] ");
    n += AU(buf + n, cap - n, (unsigned)seq);
    n += AS(buf + n, cap - n, " ");
    n += AS(buf + n, cap - n, kind);
    n += AS(buf + n, cap - n, " f=");
    n += AH8(buf + n, cap - n, (unsigned)(uintptr_t)fontObj);
    n += AS(buf + n, cap - n, " ");
    n += AS(buf + n, cap - n, "ret=");
    n += AH8(buf + n, cap - n, (unsigned)(uintptr_t)retAddr);
    n += AS(buf + n, cap - n, " (");
    n += AInt(buf + n, cap - n, x);
    n += AS(buf + n, cap - n, ",");
    n += AInt(buf + n, cap - n, y);
    n += AS(buf + n, cap - n, ") x2=");
    n += AInt(buf + n, cap - n, x2);
    n += AS(buf + n, cap - n, " end=");
    n += AInt(buf + n, cap - n, endX);
    n += AS(buf + n, cap - n, " len=");
    n += AU(buf + n, cap - n, (unsigned)len);
    n += AS(buf + n, cap - n, " pairs=");
    n += AU(buf + n, cap - n, (unsigned)nPairs);

    n += AS(buf + n, cap - n, " flags=");
    if (!flags) n += AS(buf + n, cap - n, "OK");
    if (flags & 1u)  n += AS(buf + n, cap - n, "MISS ");
    if (flags & 2u)  n += AS(buf + n, cap - n, "BADTRAIL ");
    if (flags & 4u)  n += AS(buf + n, cap - n, "CTRL ");
    if (flags & 8u)  n += AS(buf + n, cap - n, "OVERFLOW ");
    if (flags & 16u) n += AS(buf + n, cap - n, "ODD ");
    if (flags & 32u) n += AS(buf + n, cap - n, "CUST");
    n += AS(buf + n, cap - n, "\r\n");

    // ── hex 行（完整原始字节，绝不截断 —— 这是判读的根本依据）──
    n += AS(buf + n, cap - n, "     hex ");
    const int hexMax = (len > 240 ? 240 : len);
    for (int i = 0; i < hexMax && n < cap - 4; ++i)
        n += AH2(buf + n, cap - n, (unsigned char)str[i]);
    if (hexMax < len) n += AS(buf + n, cap - n, "...");
    n += AS(buf + n, cap - n, "\r\n");

    // ── txt 行（UTF-8 可读文本）──────────────────────────────
    n += AS(buf + n, cap - n, "     txt ");
    AppendCp950Utf8(buf, cap, &n, (const unsigned char*)str, hexMax);
    n += AS(buf + n, cap - n, "\r\n");

    // ── uni 行（逐字字形索引，-1 = 查不到）───────────────────
    n += AS(buf + n, cap - n, "     uni ");
    {
        const unsigned char* p = (const unsigned char*)str;
        int shown = 0;
        while (p[0] && shown < 40 && n < cap - 14) {
            if (PairU(p[0], p[1]) && p[1]) {
                n += AH2(buf + n, cap - n, p[0]);
                n += AH2(buf + n, cap - n, p[1]);
                n += AS(buf + n, cap - n, "#");
                n += AInt(buf + n, cap - n, GlyphIndex(p[0], p[1]));
                n += AS(buf + n, cap - n, " ");
                ++shown; p += 2;
                continue;
            }
            if (p[0] >= 0x80) {
                n += AH2(buf + n, cap - n, p[0]);
                n += AS(buf + n, cap - n, "? ");
                ++shown;
            }
            ++p;
        }
        if (!shown) n += AS(buf + n, cap - n, "-");
    }
    n += AS(buf + n, cap - n, "\r\n");

    // ── stk 行（调用链）──────────────────────────────────────
    n += AS(buf + n, cap - n, "     stk ");
    {
        int before = n;
        AppendStack(buf, cap, &n, frame, (uint32_t)(uintptr_t)retAddr);
        if (n == before) n += AS(buf + n, cap - n, "-");
    }
    n += AS(buf + n, cap - n, "\r\n");

    LogRaw(buf, n);
}

// ── 对外入口 ────────────────────────────────────────────────
// 诊断跑在渲染热路径上，每秒会被调用几十到几百次。这里任何一个越界读
// 都会直接把游戏崩掉 —— 而它本职是「帮用户找崩溃」，自己先崩就太讽刺了。
// 所以整段套 SEH：宁可丢一条日志，也绝不让诊断代码影响游戏运行。
void DiagText(const char* kind, const void* fontObj, const char* str,
              int x, int y, int x2, int endX, void* retAddr, uint32_t frame)
{
    if (DiagLevel() == 0) return;        // 默认关闭：不进 SEH，零开销
    static LONG errCount = 0;
    // 诊断跑在渲染热路径上（每次 put/para 都会进），必须计时 ——
    // 它内部有 VirtualQuery + 全串扫描，是最容易被忽略的卡顿源。
    // ★ 这里只能显式配对，不能上 RAII：MSVC 不允许在需要对象展开的函数里用 __try
    //   （C2712）。PerfEnd 在 __except 之后无条件调用，保证计数不漏。
    sk2::PerfBegin(sk2::PERF_DIAG);
    __try {
        DiagTextBody(kind, fontObj, str, x, y, x2, endX, retAddr, frame);
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        if (InterlockedIncrement(&errCount) <= 5)
            Log("[!] DiagText 内部异常已忽略 str=%p kind=%s\r\n", str, kind ? kind : "?");
    }
    sk2::PerfEnd(sk2::PERF_DIAG);
}

// ── 缺字形汇总 ──────────────────────────────────────────────
void DiagDumpMissing() {
    EnterCriticalSection(&g_cs);
    if (g_missN == 0) {
        LeaveCriticalSection(&g_cs);
        Log("[i] 缺字形统计：本轮没有查不到的字\r\n");
        return;
    }
    Log("\r\n########## 缺字形汇总（字形池查不到的双字节对）##########\r\n");
    for (int i = 0; i < g_missN; ++i) {
        char b[64];
        unsigned char pair[2] = { (unsigned char)(g_miss[i].code >> 8),
                                  (unsigned char)(g_miss[i].code & 0xFF) };
        int k = 0;
        k += AS(b + k, 64 - k, "[X] ");
        k += AH2(b + k, 64 - k, pair[0]);
        k += AH2(b + k, 64 - k, pair[1]);
        k += AS(b + k, 64 - k, "  cp950解: ");
        AppendCp950Utf8(b, 64, &k, pair, 2);
        k += AS(b + k, 64 - k, "  出现 ");
        k += AU(b + k, 64 - k, (unsigned)g_miss[i].count);
        k += AS(b + k, 64 - k, " 次\r\n");
        LogRaw(b, k);
    }
    Log("[i] 共 %d 种不同的字节对查不到字形\r\n", g_missN);
    Log("######################################################\r\n\r\n");

    // 再给一行紧凑清单 —— 可直接喂给 tools/gen_extra.py 批量补字形，
    // 省得从上面的明细里手工挑码位。
    char line[1400];
    int k2 = AS(line, sizeof(line), "[i] MISS-CODES: ");
    for (int i = 0; i < g_missN && k2 < sizeof(line) - 8; ++i) {
        k2 += AH2(line + k2, sizeof(line) - k2, (unsigned char)(g_miss[i].code >> 8));
        k2 += AH2(line + k2, sizeof(line) - k2, (unsigned char)(g_miss[i].code & 0xFF));
        k2 += AS(line + k2, sizeof(line) - k2, " ");
    }
    LogRaw(line, k2);
    LogRaw("\r\n", 2);
    LeaveCriticalSection(&g_cs);
}

// ── 后台刷新线程：即使游戏崩溃也留有证据 ────────────────────
// 日志是 append 且每次 WriteFile 直接落盘，所以进程被杀也不丢已写内容。
// 这里周期性输出增量，方便按时间线判断「什么时候开始出现缺字」。
static DWORD WINAPI FlusherProc(LPVOID) {
    // 最低优先级：诊断永远不与游戏抢 CPU
    SetThreadPriority(GetCurrentThread(), THREAD_PRIORITY_LOWEST);
    for (int i = 1; i <= 200; ++i) {
        Sleep(15000);
        EnterCriticalSection(&g_cs);
        int cnt = g_missN;
        LeaveCriticalSection(&g_cs);
        Log("[i] 诊断心跳 %3d: 已记录 %ld 条文本, 缺字形种类=%d\r\n", i, g_seq, cnt);
        // 频次从「每 4 次」提到「每 2 次」(30 秒)：游戏崩溃时 DLL_PROCESS_DETACH
        // 不会执行，靠轮询把证据提前落盘才是可靠的。
        if (cnt > 0 && (i % 2) == 0) DiagDumpMissing();
    }
    return 0;
}

void DiagStartFlusher() {
    // Stage < 3 时 LoadRenderCfg 不会被调用，此时 g_cs 还没初始化。
    // 这里补一次，保证下面的 FlusherProc 能安全使用临界区。
    if (!g_csReady) DiagInit(g_level);
    if (DiagLevel() == 0) return;        // 诊断没开，不必起线程
    HANDLE t = CreateThread(nullptr, 0, FlusherProc, nullptr, 0, nullptr);
    if (t) CloseHandle(t);
}

}
