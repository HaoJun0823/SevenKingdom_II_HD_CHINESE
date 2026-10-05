// hooks.cpp — text_width 双字节挂钩（Stage 2）
//
// 引擎原逻辑（IDA sub_4C0780，逐字对照）：
//   for (i=1; *Stra && i<=a3; ++i) {
//     v14 = *(uint8*)Stra;
//     if (a5==1) v14 = upper_case(v14);
//     if (v14 == 10)              { 取行最大值; 归零; ++行数; }
//     else if (v14 < 128 || v14 > 143) {
//        if (v14 == 32)           { 空格 -> 用 space_width }
//        else if (v14<first||v14>last) { 普通 -> max_width }
//        else                     { width = font_info[7*(v14-first)+1]; }
//        ... clamp 到 a4
//     }
//     else { 国家色 -> 宽 13 }
//     v12 = 累加 + inter_space;
//   }
//   返回 max(行宽)
//
// 我们的改动：把「单字节取字符」换成「双字节取字符」，
// 其余逻辑（含 clamp / 换行 / 行数统计）严格照抄，保证行为一致。
#include "pch.h"
#include "core.h"
#include "fontwidth.h"
#include "hooks.h"
#include "cjk.h"        // 逐路径耗时统计 PerfBegin/PerfEnd

using namespace sk2;

// -- 引擎辅助函数指针（通过签名定位后取地址）----------------
namespace {

// upper_case @ 0x4C28F0 —— 实测就是 toupper：
//   if (c > '`' && c < '{') return toupper(c);
// 约定为 __thiscall(short c)：ECX = this（函数体不用），栈上 1 个参数，ret 0x4。
// 用 3 参数 __fastcall 精确模拟（这正是不调用它会导致宽度算错的原因：
// a5==1 时引擎把字母转大写后再测宽，大写更宽）。
typedef short(__fastcall* FnUpperCase)(void* self, void* edx, short c);
FnUpperCase g_upperCase = nullptr;
// 注意：地址不再硬编码，改由 Loc(LOC_UPPER_CASE) 定位（见 core.cpp 的 kLocTab）。
// STEAM 版此函数在 0x4C28C0，硬编码 RVA 会调到别的函数上。

// text_width 原始地址
void*  g_textWidth = nullptr;
uint8_t g_twSaved[5] = {};
volatile LONG g_twCount = 0;
volatile LONG g_twDBCS = 0;      // 统计见过多少双字节，供验证 hook 是否命中中文
bool   g_selfTestPassed = false; // 离线自测是否通过（安装挂钩的门禁）
void*  g_twOrig = nullptr;       // 原函数跳板（前 N 字节原样回放 + 跳回），用于差分验证

// -- 差分验证 --------------------------------------------------
// 把我们的结果和「引擎原函数」的结果逐个字符比对。
// 这是最强的验证：只要 ASCII 下返回值与原函数一致，就说明
//   ① Font 字段偏移正确 ② 宽度语义正确 ③ 不会让英文排版漂移。
// 一旦有偏差，立刻打印差异，不必靠肉眼看画面。
// 原函数用跳板调用：__fastcall(font, sink, str, a3, a4, a5) 恰好等价于引擎的
// __thiscall（ECX=this，4 个栈参数，ret 0x10）。
typedef int(__fastcall* OrigTextWidthFn)(int*, void*, const char*, int, int, int);
static LONG g_diffChecked = 0;
static LONG g_diffMismatch = 0;

// 串里是否含 >=0x80 的字节
static bool HasHighByte(const char* s) {
    if (!s) return false;
    for (const unsigned char* q = (const unsigned char*)s; *q; ++q)
        if (*q >= 0x80) return true;
    return false;
}

// -- 探针 ------------------------------------------------------
// Stage 2 阶段资源仍是英文，若只统计总调用次数无法证明双字节分支正确。
// 因此记录「前若干次出现高位字节的调用」的字符串与宽度，用于人工核对。
static LONG g_probeCount = 0;
static const LONG kProbeMax = 12;
static bool g_inSelfTest = false;   // 自测期间抑制探针

// 极简无 CRT 的整数/十六进制输出，避免在 hook 里触发 sprintf_s 的
// 「参数非法即终止进程」行为（缓冲区算错就会直接杀进程）。
static int AppendUInt(char* dst, int cap, unsigned v) {
    char tmp[12];
    int n = 0;
    if (v == 0) tmp[n++] = '0';
    while (v && n < (int)sizeof(tmp)) { tmp[n++] = (char)('0' + (v % 10)); v /= 10; }
    int w = 0;
    while (n > 0 && w < cap - 1) { dst[w++] = tmp[--n]; }
    return w;
}
static int AppendHex2(char* dst, int cap, unsigned v) {
    static const char* H = "0123456789ABCDEF";
    if (cap < 3) return 0;
    dst[0] = H[(v >> 4) & 0xF];
    dst[1] = H[v & 0xF];
    return 2;
}
static int AppendStr(char* dst, int cap, const char* s) {
    int n = 0;
    while (s[n] && n < cap - 1) { dst[n] = s[n]; ++n; }
    return n;
}

static void ProbeRecord(const char* str, int width, int dbcsCount, int charCount) {
    if (!str) return;
    if (g_inSelfTest) return;      // 自测期间不写探针，避免污染日志
    // 先查上限再扫描：text_width 每秒被调用上万次，若每次都先扫 64 字节
    // 再发现「早就不记了」，纯属白烧 CPU。
    if (g_probeCount >= kProbeMax) return;
    // 只关注含高位字节（>=0x80）的串，即可能是 CJK 的输入
    bool hasHigh = false;
    for (const unsigned char* q = (const unsigned char*)str; *q && q - (const unsigned char*)str < 64; ++q)
        if (*q >= 0x80) { hasHigh = true; break; }
    if (!hasHigh) return;

    LONG idx = InterlockedIncrement(&g_probeCount);
    if (idx > kProbeMax) return;

    char buf[160];
    int n = 0;
    n += AppendStr(buf + n, sizeof(buf) - n, "[dbg] tw#");
    n += AppendUInt(buf + n, sizeof(buf) - n, (unsigned)idx);
    n += AppendStr(buf + n, sizeof(buf) - n, " w=");
    n += AppendUInt(buf + n, sizeof(buf) - n, (unsigned)width);
    n += AppendStr(buf + n, sizeof(buf) - n, " dbcs=");
    n += AppendUInt(buf + n, sizeof(buf) - n, (unsigned)dbcsCount);
    n += AppendStr(buf + n, sizeof(buf) - n, "/");
    n += AppendUInt(buf + n, sizeof(buf) - n, (unsigned)charCount);
    n += AppendStr(buf + n, sizeof(buf) - n, " \"");
    for (const unsigned char* q = (const unsigned char*)str;
         *q && n < (int)sizeof(buf) - 6; ++q) {
        n += AppendHex2(buf + n, sizeof(buf) - n, *q);
        if (n < (int)sizeof(buf) - 1) buf[n++] = ' ';
    }
    n += AppendStr(buf + n, sizeof(buf) - n, "\"\r\n");
    LogRaw(buf, n);
}

// 读取 Font 字段
inline int16_t F16(int* f, int off) { return *reinterpret_cast<int16_t*>(reinterpret_cast<uint8_t*>(f) + off); }
inline uint32_t F32(int* f, int off) { return *reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(f) + off); }

// 引擎的 FontInfo 查表：width = fontinfo[7*(ch-first)+1]
inline int EngineCharWidth(int* font, int ch) {
    int first = F16(font, font_off::FIRST_CHAR);
    int last  = F16(font, font_off::LAST_CHAR);
    if (ch < first || ch > last) return F16(font, font_off::SPACE_WIDTH);  // 引擎: 回退宽 = 同 +17 字段
    uint32_t info = F32(font, font_off::FONT_INFO);
    if (!info) return F16(font, font_off::SPACE_WIDTH);
    const uint8_t* p = reinterpret_cast<const uint8_t*>(info) +
                       7 * (ch - first) + 1;
    return *p;
}

// 单个字符的推进宽度（双字节时 lead/trail 合并算）
inline int AdvanceWidth(int* font, int lead, int trail, bool dbcs) {
    if (dbcs) return GlyphPx(font);      // 全角方块字身，与绘制侧同源
    return EngineCharWidth(font, lead);
}

// 安全写全局变量：地址必须在映像内，否则跳过并告警一次。
//
// 参数从「RVA」改成「已定位的真实地址」：line_count 现在由签名定位，
// 在 STEAM 上地址与 GOG 不同（.data 位移 +0x38），再把 RVA 传进来
// 就会写到隔壁变量上，而这种错误在日志里完全看不出来。
static bool g_warnedRange = false;
static inline bool InImage(void* p, int n) {
    uint8_t* base = Base();
    return p >= base && static_cast<uint8_t*>(p) + n <= base + 0x0C00000;
}
static inline void SafeSetInt(void* addr, int val) {
    uint8_t* p = static_cast<uint8_t*>(addr);
    if (!p || !InImage(p, 4)) {
        if (!g_warnedRange) {
            g_warnedRange = true;
            Log("[X] 全局变量 %p 越界或未定位，已跳过写入\r\n", addr);
        }
        return;
    }
    memcpy(p, &val, 4);
}
static inline void SafeAddInt(void* addr, int delta) {
    uint8_t* p = static_cast<uint8_t*>(addr);
    if (!p || !InImage(p, 4)) return;
    int v = 0;
    memcpy(&v, p, 4);
    v += delta;
    memcpy(p, &v, 4);
}
// line_count 的语义化包装：未定位时静默跳过（计数只影响排版估算，
// 不该因为定位失败把整条宽度路径打断）。
static inline void LineCountSet(int v) { SafeSetInt(Loc(LOC_G_LINE_COUNT), v); }
static inline void LineCountAdd(int d) { SafeAddInt(Loc(LOC_G_LINE_COUNT), d); }

// -- 替换实现 -----------------------------------------------
//
// ★ ABI 匹配（这是崩溃过的坑，务必理解）★
//
// 引擎的 Font::text_width @0x4C0780 是 **__thiscall**：
//     ECX = this(Font*), 栈上依次 = Str, a3, a4, a5，函数以 `ret 0x10` 收尾
//     （实测尾部字节 C2 10 00 = ret 16）
//
// MSVC 不允许在自由函数上用 __thiscall（error C3865），
// 因此用「6 参数 __fastcall」精确模拟同一 ABI：
//     第1参 → ECX（正好就是 this）
//     第2参 → EDX（引擎不用 EDX 传参，纯占位吸收）
//     其余 4 参 → 栈上，正好对应 Str/a3/a4/a5 → 编译器生成 ret 0x10
//     （已用 dumpbin 验证：C2 10 00）
//
// 之前用「5 参数 __fastcall」→ ECX=font, EDX=str, 栈只有 3 个 → ret 0x0C
//   ⇒ str 读到 EDX 的垃圾值 ⇒ 解引用崩溃；且栈少清 4 字节 ⇒ 返回地址错乱
//
// 语义说明：
//   a3 < 0        → 用 strlen(Str) 作为字节上限
//   a4 == 0       → 不限宽（引擎约定：0 = 无限制，不是"限制为0"）
//   a5 == 1       → 转大写
//
static int TextWidthImpl(int* font, const char* str, int a3, int a4, int a5);

static int __fastcall Hook_text_width(int* font, void* edx_sink,
                                      const char* str, int a3, int a4, int a5) {
    (void)edx_sink;
    return TextWidthImpl(font, str, a3, a4, a5);
}

// 运行期一次性转储真实 Font 对象，用于实证字段偏移是否正确。
// 期望（ASCII 字体）：first_char≈32, last_char≈255, font_info 非空,
//                     font_height 合理(8~24), inter_space 很小。
static void DumpFontOnce(int* font) {
    static LONG done = 0;
    if (InterlockedIncrement(&done) != 1) return;

    const uint8_t* b = reinterpret_cast<const uint8_t*>(font);
    Log("[i] --- 真实 Font 对象转储 @ %08X ---\r\n", (uint32_t)(uintptr_t)font);
    for (int off = 0; off < 40; off += 16) {
        char line[128];
        int n = _snprintf_s(line, sizeof(line), _TRUNCATE, "      +%02X:", off);
        for (int k = 0; k < 16 && off + k < 40; ++k)
            n += _snprintf_s(line + n, sizeof(line) - n, _TRUNCATE, " %02X", b[off + k]);
        n += _snprintf_s(line + n, sizeof(line) - n, _TRUNCATE, "\r\n");
        LogRaw(line, n);
    }
    Log("[i] 解释: init=%d height=%d unk11=%d unk13=%d est=%d\r\n",
        (int)b[font_off::INIT_FLAG],
        F16(font, font_off::FONT_HEIGHT),
        F16(font, font_off::UNK_11),
        F16(font, font_off::UNK_13),
        F16(font, font_off::WIDTH_EST));
    Log("[i] 解释: space=%d inter=%d first=%d last=%d info=%08X\r\n",
        F16(font, font_off::SPACE_WIDTH),
        F16(font, font_off::INTER_SPACE),
        F16(font, font_off::FIRST_CHAR),
        F16(font, font_off::LAST_CHAR),
        F32(font, font_off::FONT_INFO));
    // 合理性自检
    int first = F16(font, font_off::FIRST_CHAR);
    int last  = F16(font, font_off::LAST_CHAR);
    bool sane = (first >= 0 && first < last && last <= 0xFFFF) &&
                F32(font, font_off::FONT_INFO) != 0 &&
                (first < 128 || first > 0xFFFF);   // 不希望 first 落在乱码区间
    Log("[%s] 字段偏移合理性: first=%d last=%d\r\n", sane ? "O" : "!", first, last);
}

// 前 N 次调用的完整追踪 + 周期心跳：
// 确认 hook 到底有没有被游戏调用。
// 上一版只转储 Font、且探针只记高位字节串，结果英文环境下「一次都没输出」，
// 无法区分「hook 没生效」与「没有含中文的串」。故补充：
//   1) 前 6 次调用无条件记录（含 ASCII 串内容）
//   2) 每 1000 次调用打一次心跳，证明 hook 在持续工作
static void TraceFirstCalls(int* font, const char* str, int a3, int a4, int a5, int result) {
    static LONG n = 0;
    LONG idx = InterlockedIncrement(&n);

    if (idx <= 6) {
        char buf[220];
        int k = _snprintf_s(buf, sizeof(buf), _TRUNCATE,
                            "[dbg] call#%ld a3=%d a4=%d a5=%d -> %d len=%d \"",
                            idx, a3, a4, a5, result, str ? (int)strlen(str) : -1);
        if (k > 0 && str) {
            for (const unsigned char* q = (const unsigned char*)str;
                 *q && k < (int)sizeof(buf) - 6; ++q)
                k += _snprintf_s(buf + k, sizeof(buf) - k, _TRUNCATE, "%c",
                                 (*q >= 0x20 && *q < 0x7F) ? *q : '.');
        }
        if (k > 0) k += _snprintf_s(buf + k, sizeof(buf) - k, _TRUNCATE, "\"\r\n");
        if (k > 0) LogRaw(buf, k);
        return;
    }
    // ★ 这里原来每 1000 次调用就写一行日志。text_width 是引擎**最热**的函数
    //   （实测 15 秒内 4.4 万次），于是每秒几十次同步 WriteFile 直接压在渲染
    //   线程上 —— 点按钮时的卡顿有一部分就来自它。
    //   计数已在监控行（每 5 秒）里给出，这里不再写盘。
}

// 计时守卫：TextWidthImpl 有多个 return，用 RAII 保证每次都记账。
// 注意：本函数会被 MeasureText 从 put 路径里调用，嵌套的是不同 id 的槽位，互不覆盖。
struct TwPerfGuard {
    TwPerfGuard() { sk2::PerfBegin(sk2::PERF_TW); }
    ~TwPerfGuard() { sk2::PerfEnd(sk2::PERF_TW); }
};

static int TextWidthImpl(int* font, const char* str, int a3, int a4, int a5) {
    TwPerfGuard pg;
    InterlockedIncrement(&g_twCount);

    if (!*reinterpret_cast<int8_t*>(font)) return 0;   // 未初始化
    if (!str) return 0;

    if (!g_inSelfTest) DumpFontOnce(font);   // 首次真实调用时转储字段，实证偏移

    // 官方中文版翻译表（HD 版为空表，返回原串）——暂不接，Stage 2 先直连
    const char* p = str;
    if (a3 < 0) a3 = (int)strlen(p);

    int lineMax = 0, cur = 0, prev = 0;   // lineMax=行最大值 cur=当前行 prev=上一字宽
    LineCountSet(1);

    int spaceW  = F16(font, font_off::SPACE_WIDTH);
    int interW  = F16(font, font_off::INTER_SPACE);
    bool lastWasDBCS = false;
    int dbcsSeen = 0, charsSeen = 0;

    for (int i = 1; *p && i <= a3; ++i) {
        int lead = (unsigned char)*p;
        int trail = 0;
        bool dbcs = false;

        // -- 双字节识别 --
        // ★ 必须转 unsigned char：p 是 const char*，p[1] 是 signed char，
        //   尾字节 >= 0x80 时（如 0xA4）会变成负数，IsTrailValid 收到 -92
        //   就判为非法 —— 实测 "A4 A4"(中) 因此漏判，而 "BD 54"(確) 的尾字节
        //   0x54 是正数所以侥幸通过。自测正是靠这一条抓出了该 bug。
        const int trailU = (unsigned char)p[1];
        if ((lead >= B5_LEAD_MIN && lead <= B5_LEAD_MAX && IsTrailValid(trailU)) ||
            (lead >= CUST_LEAD_MIN && lead <= CUST_LEAD_MAX && IsTrailValid(trailU))) {
            trail = trailU;
            dbcs = true;
            InterlockedIncrement(&g_twDBCS);
        }

        // 与引擎一致：a5==1 时对每个字符走引擎自己的 toupper
        if (a5 == 1 && g_upperCase)
            lead = g_upperCase(font, nullptr, (short)lead);

        // 限宽换行判定
        if (a4 > 0 && cur > a4) {
            lineMax = a4;
            cur = prev;
            LineCountAdd(1);
        }

        int next;
        if (lead == CHAR_LF && !dbcs) {
            if (cur > lineMax) lineMax = cur;
            next = 0;
            prev = 0;
            LineCountAdd(1);        } else if (IsNationColor(lead) && !dbcs) {
            next = cur + 13;                       // 国家色条固定宽
            prev = 0;
        } else {
            if (dbcs) {
                // 档位规则与 cjk.cpp 绘制侧共用 core.h 的 GlyphPx()，
                // 保证「测量宽度」与「实际绘制宽度」永远一致。
                int pxSize = GlyphPx(font);
                next = cur + pxSize;               // 全角
                prev = pxSize;
            } else if (lead == CHAR_SPACE) {
                next = cur + spaceW;
                prev = 0;
            } else {
                int w = AdvanceWidth(font, lead, 0, false);
                next = cur + w;
                prev = w;
            }
            if (a4 > 0 && prev > a4) {              // 单字超限 -> 裁到边界
                next -= prev - a4;
                prev = a4;
            }
        }

        p += dbcs ? 2 : 1;
        cur = next + interW;
        lastWasDBCS = dbcs;
        if (dbcs) ++dbcsSeen; else ++charsSeen;
    }

    if (a4 > 0 && cur > a4)
        LineCountAdd(1);
    if (p[-1] == CHAR_LF && !lastWasDBCS)
        LineCountAdd(-1);

    int result = (lineMax <= cur) ? cur : lineMax;

    if (!g_inSelfTest) {
        // ── 差分验证：与引擎原函数比对 ──
        // 只对**纯 ASCII 串**比对：中文串上「原函数」本就该给出不同结果
        // （那正是我们要改的），混进来会产生大量预期内的噪音。
        if (g_twOrig && g_diffChecked < 300 && !HasHighByte(str)) {
            LONG k = InterlockedIncrement(&g_diffChecked);
            OrigTextWidthFn orig = (OrigTextWidthFn)g_twOrig;
            int expect = orig(font, nullptr, str, a3, a4, a5);
            if (expect != result) {
                LONG m = InterlockedIncrement(&g_diffMismatch);
                if (m <= 15)
                    Log("[X] 差分不符 #%ld: \"%.48s\" a3=%d a4=%d a5=%d 原=%d 我=%d\r\n",
                        m, str, a3, a4, a5, expect, result);
            }
            // 每 25 次给一次正向确认（只报「无误」行，便于一眼确认）
            if (k == 25 || k == 75 || k == 150 || k == 300) {
                Log("[%s] 差分验证: 已比对 %ld 次, 不符 %ld 次\r\n",
                    g_diffMismatch == 0 ? "O" : "X", k, g_diffMismatch);
            }
        }
        TraceFirstCalls(font, str, a3, a4, a5, result);
        ProbeRecord(str, result, dbcsSeen, charsSeen);
    }
    return result;
}

}  // namespace

namespace sk2 {

bool InstallTextWidth() {
    // 地址来自定位器（签名优先、RVA 兜底），这里不再自己搜签名。
    // 定位器在 Stage 1 已经跑过并打印过结果，此处只消费结论。
    g_textWidth = Loc(LOC_TEXT_WIDTH);
    if (!g_textWidth) {
        Log("[X] text_width 未定位，无法挂钩\r\n");
        return false;
    }
    uint32_t va = LocVa(LOC_TEXT_WIDTH);
    Log("[i] text_width @ %08X\r\n", va);

    // ★ 门禁：自测未通过绝不安装挂钩
    // （上次就是自测 0/4 仍然装了钩子，直接崩溃）
    if (!g_selfTestPassed) {
        Log("[X] 离线自测未通过，拒绝安装 text_width 挂钩\r\n");
        return false;
    }

    // 定位并接入引擎的 toupper（a5==1 时必须与引擎一致，否则宽度算错）
    g_upperCase = (FnUpperCase)Loc(LOC_UPPER_CASE);
    if (g_upperCase) {
        // 简单校验：toupper('a') 应得 'A'
        short t = g_upperCase(nullptr, nullptr, (short)'a');
        if (t == (short)'A') {
            Log("[O] 已接入引擎 toupper @ %08X (校验 'a'->'A')\r\n", LocVa(LOC_UPPER_CASE));
        } else {
            Log("[X] toupper 校验失败 ('a'->%d)，置空以免算错\r\n", (int)t);
            g_upperCase = nullptr;
        }
    } else {
        Log("[X] toupper 未定位，置空（宽度将不转大写）\r\n");
    }

    // ABI 校验：函数必须以 ret 0x10 收尾（thiscall + 4 栈参数）
    // 若不符说明签名搜到了别的函数，宁可不动
    {
        uint8_t* p = static_cast<uint8_t*>(g_textWidth);
        // 从函数头向后扫描前 0x300 字节内的 C2 xx xx
        bool hasRet16 = false;
        for (int i = 0x40; i < 0x300; ++i) {
            if (p[i] == 0xC2) {
                uint16_t imm = *(uint16_t*)(p + i + 1);
                if (imm == 0x10) { hasRet16 = true; break; }
            }
        }
        if (!hasRet16) {
            Log("[!] 未在函数内找到 ret 0x10，ABI 可能不符，暂不挂钩\r\n");
            return false;
        }
        Log("[i] ABI 校验通过: 找到 ret 0x10 (__thiscall + 4 栈参数)\r\n");
    }

    // 先建跳板（必须在打补丁前，跳板要复制原函数头部字节）
    // 偷 6 字节 = "push ebp; mov ebp,esp; sub esp,20h"，是完整的指令序列
    g_twOrig = BuildTrampoline(g_textWidth, 6);
    if (g_twOrig)
        Log("[i] 已建原函数跳板 @ %08X（用于差分验证）\r\n",
            (uint32_t)(uintptr_t)g_twOrig);
    else
        Log("[!] 跳板创建失败，跳过差分验证（不影响挂钩）\r\n");

    if (!InstallJump(g_textWidth, (void*)&Hook_text_width, g_twSaved)) {
        Log("[X] 安装 JMP 失败\r\n");
        return false;
    }
    LogBytes("[i] original bytes", g_twSaved, 5);
    Log("[i] now E9 %02X %02X %02X %02X %02X\r\n",
        ((uint8_t*)g_textWidth)[0], ((uint8_t*)g_textWidth)[1], ((uint8_t*)g_textWidth)[2],
        ((uint8_t*)g_textWidth)[3], ((uint8_t*)g_textWidth)[4]);
    return true;
}

long TextWidthCallCount() {
    return (long)g_twCount;
}

// 按引擎语义测量串宽。优先用「原函数跳板」（与引擎逐字节一致），
// 没有跳板时退回本模块实现。
int MeasureText(int* font, const char* s) {
    if (!font || !s) return 0;
    if (g_twOrig) return ((OrigTextWidthFn)g_twOrig)(font, nullptr, s, -1, 0, 0);
    return TextWidthImpl(font, s, -1, 0, 0);
}

bool InstallFontInfo() {
    // Stage 3：构造等效 FontInfo 池（待实现）
    Log("[!] Stage 3 尚未实现\r\n");
    return false;
}

// -- 离线自测 --------------------------------------------------
// 目的：Stage 2 阶段资源仍是英文，游戏里跑不到双字节分支。
// 用构造的假 Font 对象直接调 TextWidthImpl，验证宽度算得对不对。
// 这样不用投资源就能确认核心逻辑，后续 Stage 3 也有回归基准。
void SelfTest() {
    Log("\r\n--- 离线自测 (假 Font 对象) ---\r\n");

    // 构造一个最小 Font：只需 0/9/11/13/15/17/19/25 字段
    // 布局见 core.h 的 font_off（IDA 实证：info@25, bitmap@29）
    static uint8_t font[40] = {};
    auto set16 = [&](int off, int v) { memcpy(font + off, &v, 2); };
    auto set32 = [&](int off, uint32_t v) { memcpy(font + off, &v, 4); };

    // 造一个 FontInfo 池：first_char..last_char 每项 7 字节，width 固定 8
    static uint8_t info[7 * 256];
    for (int i = 0; i < 256; ++i) {
        info[i * 7 + 0] = 0;    // offset_y
        info[i * 7 + 1] = 8;    // width
        info[i * 7 + 2] = 16;   // height
        int32_t off = i * 16;
        memcpy(info + i * 7 + 3, &off, 4);
    }

    font[font_off::INIT_FLAG] = 1;                    // 已初始化
    set16(font_off::FONT_HEIGHT, 14);                 // +9  std_height
    set16(font_off::UNK_13, 18);                      // +13 max_height -> GlyphPx 判为 16px
    //  ★ 必须设 +13：档位判定现由 core.h 的 GlyphPx() 依 max_height 决定，
    //    若留 0 会被判成 13px，下面的 16px 期望值就会全部落空
    //    （这正是上一版自测失败的根因）。
    set16(font_off::SPACE_WIDTH, 8);                  // 空格/回退宽（同一字段 +17）
    set16(font_off::FIRST_CHAR, 32);
    set16(font_off::LAST_CHAR, 255);
    set16(font_off::INTER_SPACE, 1);
    set32(font_off::FONT_INFO, (uint32_t)(uintptr_t)info);

    int* f = (int*)font;
    // 引擎语义：每字符推进 = 字符宽 + inter_space；a4=0 表示不限宽
    // （注意 a4 是"限宽"，0 = 无限制 —— 之前误传 -1 导致换行分支误触发）
    struct Case { const char* label; const char* bytes; int expect; };
    const Case cases[] = {
        { "ASCII  \"AB\"",          "AB",                    8 + 1 + 8 + 1 },
        { "DBCS   \"BD 54\"(確)",   "\xBD\x54",              16 + 1 },
        { "MIX    \"BD 54 41\"",    "\xBD\x54" "A",          16 + 1 + 8 + 1 },
        { "DBCS2  \"A4 A4\"(中)",   "\xA4\xA4",              16 + 1 },
        // 下面两条专门覆盖「高位尾字节」——signed char 坑的回归用例
        { "HITRAIL \"A1 A1\"",      "\xA1\xA1",              16 + 1 },
        { "HITRAIL2 \"C1 FE\"",     "\xC1\xFE",              16 + 1 },
        { "CUSTOM  \"90 40\"",      "\x90\x40",              16 + 1 },
        { "TRAIL7E \"A1 7E\"",      "\xA1\x7E",              16 + 1 },
        { "SPACES  \"A  B\"",       "A  B",                  8+1 + 8+1 + 8+1 + 8+1 },
        { "MIXED  \"A4 A4 41 A4 A4\"", "\xA4\xA4" "A" "\xA4\xA4", (16+1)*2 + (8+1) },
        { "EMPTY  \"\"",            "",                      0 },
    };
    int pass = 0, fail = 0;
    g_inSelfTest = true;

    // 档位规则单元校验：GlyphPx 依 max_height(+13) 分档，两侧（测量/绘制）共用
    {
        const struct { int mh, want; } px[] = {
            { 0,13 },{ 10,13 },{ 15,13 },{ 16,16 },{ 18,16 },{ 23,16 },{ 24,24 },{ 30,24 },
        };
        for (const auto& c : px) {
            set16(font_off::UNK_13, c.mh);
            int got = GlyphPx(f);
            bool ok = (got == c.want);
            ok ? ++pass : ++fail;
            Log("[%s] 档位 max_h=%-3d -> %dpx (期望 %d)\r\n",
                ok ? "O" : "X", c.mh, got, c.want);
        }
        set16(font_off::UNK_13, 18);   // 复位，供下面宽度用例使用
    }
    for (const auto& c : cases) {
        // a3 = -1 让实现自行 strlen；a4 = 0 不限宽；a5 = 0 不转大写
        int got = TextWidthImpl(f, c.bytes, -1, 0, 0);
        bool ok = (got == c.expect);
        ok ? ++pass : ++fail;
        Log("[%s] %-24s 期望 %3d  实得 %3d\r\n", ok ? "O" : "X", c.label, c.expect, got);
    }
    g_inSelfTest = false;
    Log("[i] 自测结果: %d 通过, %d 失败\r\n", pass, fail);
    if (fail == 0)
        Log("[O] 双字节宽度逻辑正确\r\n");
    else
        Log("[X] 宽度逻辑有误 —— 将不安装挂钩（避免崩溃）\r\n");
    g_probeCount = 0;      // 清掉自测产生的探针记录
    g_selfTestPassed = (fail == 0);
}

}  // namespace sk2
