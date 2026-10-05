// core.h — 核心定义：地址签名、日志、挂钩原语
#pragma once

#include <windows.h>
#include <cstdio>
#include <cstdint>

// -------------------------------------------------------------
// 目标：Seven Kingdoms 2 HD (GOG 版 7K2.exe, x86, ImageBase 0x400000)
//
// 设计原则：不硬编码绝对地址，全部用「字节签名」在 .text 段内搜索。
// 这样即使 EXE 有任何位移（不同版本 / GOG 更新 / ASLR delta）也能自定位。
// -------------------------------------------------------------

namespace sk2 {

// -- 挂钩点定义 -----------------------------------------------
// 签名取自 IDA 反汇编，标注了每个字节的语义（相对跳转/常量/调用目标）。

// Font::text_width  @ 0x4C0780
// 全部签名均已用 Python 在真实 7K2.exe 上验证：唯一命中且地址精确匹配。
constexpr uint8_t SIG_TEXT_WIDTH[] = {
    0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x20,              // push ebp; mov ebp,esp; sub esp,20h
    0x89, 0x4D, 0xF0,                                // mov [ebp-10h],ecx
    0xC7, 0x45, 0xF8, 0x00, 0x00, 0x00, 0x00,        // mov [ebp-8],0
    0xC7, 0x45, 0xEC, 0x00, 0x00, 0x00, 0x00,        // mov [ebp-14h],0
    0xC7, 0x45, 0xF4, 0x00, 0x00, 0x00, 0x00,        // mov [ebp-0Ch],0
    0x8B, 0x45, 0xF0, 0x0F, 0xBE, 0x08,              // mov eax,[ebp-10h]; movsx ecx,byte[eax]
    0x85, 0xC9, 0x75, 0x08                           // test ecx,ecx; jnz +8
};
constexpr int SIG_TEXT_WIDTH_LEN = sizeof(SIG_TEXT_WIDTH);

// Font::put  @ 0x4C0AE0
// 与 text_width 结构同构，靠 sub esp,24h（vs 20h）区分。
constexpr uint8_t SIG_PUT[] = {
    0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x24,              // sub esp,24h  <- 关键差异
    0x89, 0x4D, 0xF4,                                // mov [ebp-0Ch],ecx
    0x8B, 0x45, 0xF4, 0x0F, 0xBE, 0x08,              // mov eax,[ebp-0Ch]; movsx ecx,byte[eax]
    0x85, 0xC9, 0x75, 0x08                           // test ecx,ecx; jnz +8
};
constexpr int SIG_PUT_LEN = sizeof(SIG_PUT);

// Font::put_paragraph  @ 0x4C1480
// 第三个分支是 jz(短跳 74 xx)，且 sub esp,30h。
constexpr uint8_t SIG_PUT_PARAGRAPH[] = {
    0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x30,              // sub esp,30h
    0x89, 0x4D, 0xF0,                                // mov [ebp-10h],ecx
    0x8B, 0x45, 0xF0, 0x0F, 0xBE, 0x08,              // mov eax,[ebp-10h]
    0x85, 0xC9, 0x74                                 // test ecx,ecx; jz(短)
};
constexpr int SIG_PUT_PARAGRAPH_LEN = sizeof(SIG_PUT_PARAGRAPH);

// Font::center_put  @ 0x4C1140
// sub esp,0Ch + push esi 单独不足以唯一标识（0x4C11F0 也匹配），
// 因此延伸到三个 push 0（居中前画底框）。
constexpr uint8_t SIG_CENTER_PUT[] = {
    0x55, 0x8B, 0xEC, 0x83, 0xEC, 0x0C,              // sub esp,0Ch
    0x56,                                            // push esi
    0x89, 0x4D, 0xF8,                                // mov [ebp-8],ecx
    0x8B, 0x75, 0x10, 0x2B, 0x75, 0x08,              // mov esi,[ebp+arg_8]; sub esi,[ebp+arg_0]
    0x83, 0xC6, 0x01,                                // add esi,1
    0x6A, 0x00, 0x6A, 0x00, 0x6A, 0xFF               // push 0; push 0; push -1
};
constexpr int SIG_CENTER_PUT_LEN = sizeof(SIG_CENTER_PUT);

// ══════════════════════════════════════════════════════════════
// 定位器：把所有「引擎函数入口」和「引擎全局变量」都变成签名可定位
// ══════════════════════════════════════════════════════════════
//
// 为什么必须做：GOG 版与 STEAM 版是同一份源码的两次构建，但
//     .text 里的函数整体位移 +0x30（GOG = STEAM + 0x30）
//     .data 全局  整体位移 +0x38
//     .rdata 全局 整体位移 +0x20
// 于是任何硬编码 RVA 在另一个版本上都是错地址 → 插件在 STEAM 上必然出错。
//
// 两级定位策略：
//   ① 函数：直接通配符签名搜 .text，要求两版都唯一命中（已逐一验证 n=1）；
//   ② 全局变量：绝对地址立即数会随版本变化，直接搜立即数在 STEAM 上 n=0。
//      改为「先签名定位宿主函数/指令，再在匹配点固定偏移处读 imm32」——
//      运行期读到的立即数已被 loader 重定位修正，天然跟随版本与 ASLR。
//
// RVA 兜底：签名未命中时退回 RVA（GOG 已知可用），保证 GOG 永不倒退。
// 每个兜底值都是「签名未命中」时的最后手段，命中日志会写明走了哪条路。
//
// 段范围（PE 段表，GOG 版）：.rdata [25A000,47E448)  .data [27E000,8E5C20)
namespace loc_kind {
constexpr int FUNC    = 0;   // 匹配点(+delta) = 函数入口
constexpr int PTR     = 1;   // 匹配点+delta 处的 imm32 = 全局变量运行期地址
constexpr int FIXEDVA = 2;   // 不用签名，直接用兜底 RVA（两版地址相同且无法定位）
// 注意：不能叫 CONST —— windef.h 把 CONST 定义成 const，会被宏替换掉。
}

// 定位目标。命名 = 引擎语义，而不是地址。
enum LocId {
    // ── 函数入口 ──
    LOC_TEXT_WIDTH = 0,   // Font::text_width      测量串宽（最热函数）
    LOC_PUT,              // Font::put             正文绘制
    LOC_PUT_PARAGRAPH,    // Font::put_paragraph   段落排版
    LOC_CENTER_PUT,       // Font::center_put      居中绘制
    LOC_PUT_CHAR,         // Font::put_char        单字绘制（教程提示）
    LOC_UPPER_CASE,       // engine toupper        a5==1 时宽度必须同源
    LOC_PUT_ASCII,        // 逐字节 ASCII 绘制（工具提示）
    LOC_PUT_ASCII2,       // 同构的另一条逐字节绘制
    LOC_PUT_ASCII_CH,     // 上面那条的单字原语（不挂钩，直呼）
    LOC_PUT_ASCII2_CH,    // 同构单字原语（不挂钩，直呼）
    LOC_BLIT8,            // 16bpp 字形 blit(surf,stride,x,y,bmp,pal)
    LOC_PUT_BMP,          // put_bitmap(buf,x,y,bmp)
    LOC_PUT_WRAP,         // 居中多行文本（按字断行）
    // ── 全局变量 ──
    LOC_G_SCREEN_W,       // 逻辑画布宽（1280）
    LOC_G_SCREEN_H,       // 逻辑画布高（960）
    LOC_G_WIN_FLAG,       // 窗口模式标志
    LOC_G_LINE_COUNT,     // 引擎的「已写入行数」计数
    LOC_G_HYPER_COUNT,    // 超链接书签个数
    LOC_G_HYPER_ARRAY,    // 超链接书签数组（每项 14 字节）
    LOC_G_FONT_PAL,       // 字形调色板指针
    LOC_G_USE_BACK,       // 使用后台缓冲标志
    LOC_G_ACTIVE_BUF,     // 活动绘制缓冲区对象指针
    LOC_G_OEM_TABLE,      // cp437->Latin-1 转换表基址（有效段 +0x80）
    LOC_EXE_LABELS,       // exe 内置 UI 标签连续字符串块
    LOC_N
};

// 已定位地址表（core.cpp 定义）。未命中或未越界校验的项为 nullptr。
extern void* g_locAddr[LOC_N];

// 取已定位地址。inline 直读数组：热路径（逐字形 PutBmp / ScreenW）
// 也要用它，不能有函数调用开销。
inline void* Loc(LocId id) { return g_locAddr[id]; }

// 按语义取全局变量地址的强类型包装。
// 为什么不直接散落 reinterpret_cast：这些全局里 screen_w/h 是 int、
// win_flag/use_back 是 char/byte、hyper_count 是 WORD。类型写散在各处
// 极易写错宽度（写错 → 相邻变量被改 → 极难查的偶发崩溃）。
inline int*   LocInt(LocId id)   { return reinterpret_cast<int*>(g_locAddr[id]); }
inline short* LocShort(LocId id) { return reinterpret_cast<short*>(g_locAddr[id]); }
inline char*  LocChar(LocId id)  { return reinterpret_cast<char*>(g_locAddr[id]); }
inline uint8_t*      LocByte(LocId id) { return reinterpret_cast<uint8_t*>(g_locAddr[id]); }
inline const uint8_t* LocByteC(LocId id) { return reinterpret_cast<const uint8_t*>(g_locAddr[id]); }

const char* LocName(LocId id);   // 目标名（日志用）
uint32_t    LocVa(LocId id);     // 化成 IDA 视角 VA，便于和反汇编逐字对照
int         LocateAll();         // 定位全部目标，返回命中数（幂等）

// ── 兜底 RVA（= IDA VA - 0x400000）──────────────────────────
// 注意：0x8D7F24 这种「看起来像 RVA」的值其实是 VA，必须减掉 0x400000，
//       写错会越界到映像之外，读写都是未定义行为。
constexpr uint32_t RVA_TEXT_WIDTH      = 0x0C0780;
constexpr uint32_t RVA_PUT             = 0x0C0AE0;
constexpr uint32_t RVA_PUT_PARAGRAPH   = 0x0C1480;
constexpr uint32_t RVA_CENTER_PUT      = 0x0C1140;
constexpr uint32_t RVA_PUT_CHAR        = 0x0C0FE0;
constexpr uint32_t RVA_UPPER_CASE      = 0x0C28F0;
constexpr uint32_t RVA_PUT_ASCII       = 0x0C2110;
constexpr uint32_t RVA_PUT_ASCII2      = 0x0C1F40;
constexpr uint32_t RVA_PUT_ASCII_CH    = 0x0C2090;
constexpr uint32_t RVA_PUT_ASCII2_CH   = 0x0C1EE0;
constexpr uint32_t RVA_BLIT8           = 0x003080;
constexpr uint32_t RVA_PUT_BMP         = 0x0C2A60;
constexpr uint32_t RVA_PUT_WRAP        = 0x0C1A80;
constexpr uint32_t RVA_SCREEN_W        = 0x2862A4;  // dword_6862A4  .rdata
constexpr uint32_t RVA_SCREEN_H        = 0x2862A8;  // dword_6862A8  .rdata
constexpr uint32_t RVA_WINDOW_FLAG     = 0x2864B3;  // byte_6864B3   .rdata
constexpr uint32_t RVA_LINE_COUNT      = 0x4D7F24;  // dword_8D7F24  .data
constexpr uint32_t RVA_HYPER_COUNT     = 0x4D7D78;  // word_8D7D78   .data
constexpr uint32_t RVA_HYPER_ARRAY     = 0x4D7D80;  // unk_8D7D80    .data
constexpr uint32_t RVA_FONT_PAL        = 0x29CFE8;  // dword_69CFE8  .rdata
constexpr uint32_t RVA_USE_BACK        = 0x8E3492;  // byte_CE3492   .data
constexpr uint32_t RVA_ACTIVE_BUF      = 0x28123C;  // off_68123C    .rdata
constexpr uint32_t RVA_OEM_TABLE       = 0x281028;  // byte_681028   .rdata
constexpr uint32_t RVA_EXE_LABELS      = 0x263A24;  // VA 0x663A24   .rdata

// -- Font 对象字段偏移 ------------------------------------------
//
// 来源：三个函数（text_width / put / put_paragraph）的 IDA 反编译交叉验证，
// 三者在字段访问上完全一致，可信。
//
// ★ 曾经踩的坑：早期版本把 SPACE_WIDTH 写成 11、FIRST_CHAR 写成 15，
//   整体错位了一格，导致读到的字段全错 → 挂钩后英文排版明显错乱。
//   教训：字段偏移必须逐个函数核对，不能凭结构体推断。
//
// 未能确定含义的字段（+11 / +13 / +15）保留标注，暂不使用：
//   +15 在 put 中作为「每字宽度估算」参与右边距计算。
namespace font_off {
constexpr int INIT_FLAG    =  0;   // byte   为 0 表示未初始化
constexpr int NEXT_TEXT    =  1;   // char*  put_paragraph 写回
constexpr int NEXT_Y       =  5;   // WORD
constexpr int LINE_COUNT   =  7;   // WORD
constexpr int FONT_HEIGHT  =  9;   // WORD   点阵档位判定（<16→13px, <24→16px, else 24px）
constexpr int UNK_11       = 11;   // WORD   用途未明
constexpr int UNK_13       = 13;   // WORD   用途未明
constexpr int WIDTH_EST    = 15;   // WORD   put 中用于估算右边距
constexpr int SPACE_WIDTH  = 17;   // WORD   ★ 空格宽，同时也是「越界字」的回退宽
constexpr int INTER_SPACE  = 19;   // WORD   每字之后的额外间距
constexpr int FIRST_CHAR   = 21;   // WORD   ★ FontInfo 表起始码位
constexpr int LAST_CHAR    = 23;   // WORD   ★ FontInfo 表结束码位
constexpr int FONT_INFO    = 25;   // DWORD* ★ FontInfo 数组基址（7 字节/项）
constexpr int FONT_BITMAP  = 29;   // DWORD* 位图池基址
}

// ── 中文点阵档位的唯一权威判定 ─────────────────────────────
// ★ cjk.cpp（绘制）与 hooks.cpp（宽度测量）必须用同一函数，
//   否则「按 A 进位、按 B 绘制」→ 相邻字重叠 = 重影。
//
// 依据 max_height(+13)：FNT_TBLK 实测 std_h(+9)=14、max_h(+13)=18 → 16px。
// 与旧工程 hook_dll.c 的 font_px 规则、阈值完全一致（它用的是 +0x0D）。
//
// 为什么默认 16px 而不是 13px：13px 宋体点阵笔画多为 1px，「單/遊/戲/疆」
// 这类密字会粘连成黑块（实测截图与字库点阵逐像素一致，是点阵本身的密度问题，
// 不是渲染 bug）。16px 档内部留白充分，可读性显著更好。
inline int g_glyphPxOverride = 0;      // 0 = 自动；13/16/24 可覆盖（render.ini: size=）
inline bool g_glyphShadow = false;      // 是否给中文字形补 1px 偏移阴影（默认关）
inline bool g_dbcsWidthPatch = true;    // 是否把 FontInfo 里 0x81+ 槽位宽度补成全角宽

// ── 逐条绘制路径的开关（render.ini，用于崩溃二分定位）──────────
// 默认全部开启。关掉某条 → 该条路径完全交回引擎原函数（中文不画/不换行），
// 其余路径不变。这样「资源是中文、但某条自绘不参与」可单独验证。
inline bool g_drawEnabled    = true;    // draw=0    : Font::put / 段落 / 逐字节 全不自绘
inline bool g_putAsciiEnabled= true;    // puta=0    : 不接管 0x4C2110 / 0x4C1F40
inline bool g_wrapEnabled    = true;    // wrap=0    : 不接管 0x4C1A80 居中换行
inline bool g_paraEnabled    = true;    // para=0    : 不接管 put_paragraph
inline bool g_hyperEnabled   = true;    // hyp=0     : 段落里不写引擎的超链接数组
// 逐画布边界：自绘时把上界取 min(全局屏宽, 该 surface 的 stride/2)
inline bool g_strideClamp    = true;    // clamp=0   : 退回只用全局屏宽（旧行为）

inline int GlyphPx(const int* f) {
    if (g_glyphPxOverride) return g_glyphPxOverride;
    const short mh = *reinterpret_cast<const short*>(
        reinterpret_cast<const uint8_t*>(f) + font_off::UNK_13);
    return mh < 16 ? 13 : (mh < 24 ? 16 : 24);
}

// FontInfo 条目结构（7 字节）
//   int8 offset_y; uint8 width; uint8 height; int32 bitmap_offset;
constexpr int FONTINFO_SIZE = 7;

// -- 工具函数 -------------------------------------------------

// 在 [start, start+size) 内搜索签名
void* FindSignature(void* start, size_t size, const uint8_t* sig, int sigLen);

// 搜索整个主模块的 .text 段
void* FindInText(const uint8_t* sig, int sigLen);

// ── 通配符签名（十六进制文本）────────────────────────────────
// 形态："55 8B EC 83 EC 20 89 4D ? ? ? ?"，'?' 为单字节通配。
//
// 为什么用文本而不是 ready 字节数组：签名要在 GOG/Steam 两个构建间复用，
// 必须逐字节通配掉「相对调用位移 / 栈帧偏移 / 随版本变化的绝对立即数」。
// 文本形态可以直接从 IDA 反汇编里剪切粘贴，也方便在注释里标注每个字节
// 的语义；解析开销只发生一次（定位阶段），不在热路径。
//
// 单字节通配用 '?'，两个十六进制字符之间的空格可有可无。
void* FindInTextPat(const char* hexPat);
void* FindSignaturePat(void* start, size_t size, const char* hexPat);
void* FindInImagePat(const char* hexPat);   // 全映像（含 .rdata/.data）

// 基址换算
//
// RVA (Relative Virtual Address) 的定义就是「相对映像基址的偏移」，
// 所以：实际地址 = 实际基址 + Rva。ASLR 已经体现在 Base() 里了，不要再加 Delta。
//
// 实测（base=0x00AB0000, dword_6862A4 的 RVA=0x2862A4）：
//   Base() + 0x2862A4         = 0x00D362A4  ✓ 落在 .data RVA 段 [27E000,8E5C20] 内
//   Base() + Delta() + 0x2862A4 = 0x013E62A4  ✗ 多加 0x6B0000，越界
//
// 若要换算成「IDA 里看到的首选 VA」，用 Vip()。
inline uint8_t* Base() { return reinterpret_cast<uint8_t*>(GetModuleHandleA(nullptr)); }
inline uint32_t Delta() { return reinterpret_cast<uint32_t>(Base()) - 0x400000u; }
inline void* Rva(uint32_t rva) { return Base() + rva; }
inline uint32_t Vip(uint32_t rva) { return 0x400000u + rva; }   // IDA 视角的首选 VA

// 校验指针是否落在主模块映像内（用于挂钩前的安全检查）
inline bool InImageRange(const void* p, size_t n) {
    const uint8_t* b = Base();
    const uint8_t* q = static_cast<const uint8_t*>(p);
    return q >= b && q + n <= b + 0x0C00000;
}

// 日志（写 update\ 或 scripts\ 或游戏根目录，路径为纯 ASCII 避免编码问题）
void InitLog();
void Log(const char* fmt, ...);
void LogBytes(const char* tag, const void* p, int n);
void CloseLog();
const char* LogPath();
void LogRaw(const char* buf, int len);   // 原样写入（探针高频路径用，免格式化和 1KB 截断）
long LogWriteCount();                    // 日志 WriteFile 次数（IO 压力指标）
long long LogByteCount();                // 日志累计写入字节数
void LogEmergencyStop(const char* why);  // 强制静音日志（熔断收尾）
int  LogIsMuted();
long LogDroppedCount();

// -- 挂钩原语 -------------------------------------------------

// 在 target 处写 5 字节 JMP rel32，返回原始字节用于回填
bool InstallJump(void* target, void* hook, uint8_t* savedBytes);

// JMP 跳板：把 hook 调用后再跳回 target+5
// 用法：jmp [g_trampoline]  ->  push addr; ret  或直接构造
void* BuildTrampoline(void* target, size_t stealSize);

}  // namespace sk2
