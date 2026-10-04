// cjk.cpp — 中文渲染（Stage 3）
//
// 设计要点
// --------
// 引擎的字形表按「单字节」索引（FontInfo[ch-first]），最多 256 个槽位，
// 装不下 5317 个汉字 —— 所以光注入 FontInfo 不可能渲染中文，必须自己画。
//
// 本模块的做法：
//   1. 挂钩 Font::put；**纯 ASCII 串直接转交原函数**（保证英文排版零回归）
//   2. 含双字节的串分段处理：ASCII 段仍走原函数，中文对由我们自绘
//   3. 自绘走引擎自己的 put_bitmap（0x4C2A60），复用它的调色板/透明色处理
//   4. 背景清除不调用额外引擎函数，而是用 put_bitmap 填一块纯色位图
//      —— 这样只需 1 个引擎 API，风险最小
//
// 字形数据来自 fontdata.h（旧工程生成）：Big5/custom 双表 → 5317 个宋体点阵，
// 13/16/24 三档，1bpp 掩码 + (1,1) 阴影。
//
// ★ 引擎地址均为本机 GOG 版（7K2.exe, ImageBase 0x400000）实测，
//   与旧工程的 Steam 版不同（Font 函数整体位移），不可混用。
#include "pch.h"
#include "core.h"
#include "cjk.h"
#include "hooks.h"
#include "fontdata.h"     // 提供 big5idx / custidx / goff* / gpool*（无 include guard，只在此包含）
#include "fontdata_extra.h"  // 补充字形表（主表未收录的新增译文用字）
#include "fontdata_std.h"    // STD.SET 专用码位表（引擎映射表无法还原的字节）
#include "diag.h"            // 乱码诊断日志（render.ini: debug=1/2/3）
#include <intrin.h>
#include <cstring>
#include <cstdlib>

using namespace sk2;

// ── 字形索引与点阵（fontwidth.h 声明的对外接口）─────────────
// 注意：必须放在 sk2 命名空间并具外部链接，hooks.cpp 的宽度计算会用到。
namespace sk2 {

int GlyphIndex(int lead, int trail) {
    int ti;
    if (trail >= 0x40 && trail <= 0x7E)      ti = trail - 0x40;
    else if (trail >= 0xA1 && trail <= 0xFE) ti = 63 + (trail - 0xA1);
    else return -1;

    if (lead >= CUST_LEAD_MIN && lead < CUST_LEAD_MIN + CUST_LEAD_COUNT) {
        unsigned short v = custidx[(lead - CUST_LEAD_MIN) * B5_TRAIL_COUNT + ti];
        return v ? (int)v - 1 : -1;
    }
    int gi = -1;
    if (lead >= B5_LEAD_MIN && lead <= B5_LEAD_MAX) {
        unsigned short v = big5idx[(lead - B5_LEAD_MIN) * B5_TRAIL_COUNT + ti];
        if (v) gi = (int)v - 1;
    }
    if (gi >= 0) return gi;

    const unsigned short code = (unsigned short)((lead << 8) | trail);

    // STD.SET 专用码位：这些码位只出现在 STD.SET 里（fix_stdset.py 写入），
    // 映射到主字库的既有字形，不占用新的字形池。
    for (int i = 0; i < STD_N; ++i)
        if (g_stdCode[i] == code) return (int)g_stdGlyph[i];

    // 主表未收录 —— 查补充字形表（索引空间 = N_CHARS + i）
    // 这些是新增译文才用到的字（如 课/碎/阀/陲），主表字符集来自旧译文语料。
    for (int i = 0; i < EXTRA_N; ++i)
        if (g_extraCode[i] == code) return N_CHARS + i;

    return -1;
}

const uint8_t* GlyphMask(int gi, int px) {
    if (gi < 0) return nullptr;
    if (gi >= N_CHARS) {                     // 补充表
        const int e = gi - N_CHARS;
        if (e >= EXTRA_N) return nullptr;
        if (px == 13) return g_extraPool13 + g_extraOff13[e];
        if (px == 16) return g_extraPool16 + g_extraOff16[e];
        return g_extraPool24 + g_extraOff24[e];
    }
    if (px == 13) return gpool13 + goff13[gi];
    if (px == 16) return gpool16 + goff16[gi];
    return gpool24 + goff24[gi];
}

}  // namespace sk2

using sk2::GlyphIndex;
using sk2::GlyphMask;

// ── 引擎地址（RVA = IDA VA - 0x400000）──────────────────────
namespace {

constexpr uint32_t RVA_PUT_BMP    = 0x0C2A60;  // sub_4C2A60  put_bitmap(buf, x, y, bmp)
constexpr uint32_t RVA_PUT_CHAR   = 0x0C0FE0;  // Font::put_char（单字，教程提示路径）
constexpr uint32_t RVA_ACTIVE_BUF = 0x28123C;  // off_68123C  活动绘制缓冲区对象指针
constexpr uint32_t RVA_USE_BACK   = 0x8E3492;  // byte_CE3492 使用后台缓冲标志
constexpr uint32_t RVA_SCREEN_W   = 0x2862A4;  // dword_6862A4 逻辑画布宽（1280）
constexpr uint32_t RVA_SCREEN_H   = 0x2862A8;  // dword_6862A8 逻辑画布高（960）

// ── 第 4/5 条文字路径（IDA 交叉引用实证，详见文件末尾注释）────
constexpr uint32_t RVA_PUT_ASCII    = 0x0C2110;  // sub_4C2110 逐字节 ASCII 绘制（工具提示）
constexpr uint32_t RVA_PUT_ASCII_CH = 0x0C2090;  // sub_4C2090 上面那条的单字原语
constexpr uint32_t RVA_PUT_ASCII2   = 0x0C1F40;  // sub_4C1F40 同构的另一个逐字节绘制
constexpr uint32_t RVA_PUT_ASCII2_CH= 0x0C1EE0;  // sub_4C1EE0 上面那条的单字原语
constexpr uint32_t RVA_BLIT8        = 0x003080;  // sub_403080 16bpp 字形 blit(surf,stride,x,y,bmp,pal)
constexpr uint32_t RVA_FONT_PAL     = 0x29CFE8;  // dword_69CFE8 字形调色板

typedef int(__fastcall* FN_PUT_BMP)(void* bufObj, void* edx, int x, int y, void* bmp);
typedef int(__fastcall* FN_PUT)(int* f, void* edx, int x, int y,
                                const char* s, char clearBack, int x2, int cap);
// __thiscall(this, surf, stride, x, y, str)  -> ret 0x14
typedef int(__fastcall* FN_PUT_ASCII)(int* f, void* edx, int surf, int stride,
                                      int x, int y, const char* s);
// __thiscall(this, surf, stride, x, y, u16 ch) -> ret 0x14
typedef int(__fastcall* FN_PUT_ASCII_CH)(int* f, void* edx, int surf, int stride,
                                         int x, int y, int ch);
// __stdcall(surf, stride, x, y, bmp8bpp, palette)，0xFF = 透明
typedef int(__stdcall* FN_BLIT8)(int surf, int stride, int x, int y,
                                 const void* bmp, int pal);

// 第 5 条路径：居中多行文本（只在空格处断行）@0x4C1A80
// ECX=Font，栈上 8 个参数 -> ret 0x20（无 EDX 参数）
constexpr uint32_t RVA_PUT_WRAP = 0x0C1A80;
typedef int(__fastcall* FN_PUT_WRAP)(int* f, void* edx, int x1, int y1, int x2, int y2,
                                     const char* str, int lead, int draw, int size);

// Font 字段（与 core.h 的 font_off 一致，已由差分验证确认）
inline int16_t F16(int* f, int off) {
    return *reinterpret_cast<int16_t*>(reinterpret_cast<uint8_t*>(f) + off);
}
inline uint32_t F32(int* f, int off) {
    return *reinterpret_cast<uint32_t*>(reinterpret_cast<uint8_t*>(f) + off);
}

void* ActiveBuf() {
    return *reinterpret_cast<void**>(Rva(RVA_ACTIVE_BUF));
}
bool UseBackBuf() {
    return *reinterpret_cast<char*>(Rva(RVA_USE_BACK)) != 0;
}

// VgaBuf 字段（sub_4C2A60 反编译实证：
//   put_bitmap(this,x,y,bmp) -> sub_403080(*(this+66), *(this+67), x, y, bmp, pal)
// 即 +66*4=264 是像素缓冲指针，+67*4=268 是行距字节数）
inline uint8_t* VgaPixels(const void* vb) {
    return vb ? (uint8_t*)(uintptr_t)(*reinterpret_cast<const uint32_t*>(
        reinterpret_cast<const uint8_t*>(vb) + 264)) : nullptr;
}
inline int VgaPitch(const void* vb) {
    return vb ? *reinterpret_cast<const int*>(
        reinterpret_cast<const uint8_t*>(vb) + 268) : 0;
}

// ★ 提交页探测：判断像素矩形是否整块落在「已提交」内存里。
//   sub_403080 一丝一毫都不裁剪（v8 = base + 2*x + y*stride 直接写），
//   所以任何一次坐标算错都会写穿画布、踩坏堆 —— 而堆被踩坏的表现正是
//   后续任意位置拿到野指针（实测：精灵 RLE 解码器读飞 ~1MB 撞到未提交页）。
//   这里用 VirtualQuery 问 OS 要该页的真实提交范围，宁可不画也绝不写穿。
static bool RectCommitted(const uint8_t* base, int stride, int x0, int y0, int x1, int y1) {
    if (!base || stride <= 0 || x0 < 0 || y0 < 0 || x1 < x0 || y1 < y0) return false;
    const uint8_t* p0 = base + 2 * (size_t)x0 + (size_t)y0 * stride;
    const uint8_t* p1 = base + 2 * (size_t)x1 + (size_t)y1 * stride;
    MEMORY_BASIC_INFORMATION mi = {};
    if (!VirtualQuery((void*)p0, &mi, sizeof(mi))) return false;
    if (!(mi.State & MEM_COMMIT)) return false;
    const uint8_t* lo = (const uint8_t*)mi.BaseAddress;
    const uint8_t* hi = lo + mi.RegionSize;
    return p0 >= lo && p1 < hi;
}
// 逻辑画布尺寸（引擎在窗口模式下会把 UI 居中，所以坐标已是最终空间）
inline int ScreenW() {
    int v = *reinterpret_cast<const int*>(Rva(RVA_SCREEN_W));
    return (v > 16 && v <= 4096) ? v : 1280;      // 未初始化时退回 1280x960
}
inline int ScreenH() {
    int v = *reinterpret_cast<const int*>(Rva(RVA_SCREEN_H));
    return (v > 16 && v <= 4096) ? v : 960;
}
void PutBmp(void* buf, int x, int y, void* bmp) {
    if (!buf) return;
    ((FN_PUT_BMP)Rva(RVA_PUT_BMP))(buf, nullptr, x, y, bmp);
}

// ── 双字节判定（与 fontwidth.h 同义，此处独立实现避免宏冲突）──
inline bool TrailOk(int t) { return (t >= 0x40 && t <= 0x7E) || (t >= 0xA1 && t <= 0xFE); }

inline bool IsPairU(unsigned char lead, unsigned char trail) {
    if (!TrailOk(trail)) return false;
    if (lead >= CUST_LEAD_MIN && lead < CUST_LEAD_MIN + CUST_LEAD_COUNT) return true;
    return lead >= B5_LEAD_MIN && lead <= B5_LEAD_MAX;
}

bool HasDBCS(const char* s) {
    if (!s) return false;
    for (const unsigned char* p = (const unsigned char*)s; *p; ++p) {
        if (IsPairU(*p, p[1])) return true;
    }
    return false;
}

// ── 字号档位 ────────────────────────────────────────────────
// 判定规则唯一权威在 core.h 的 GlyphPx()（依 max_height +13），
// cjk.cpp 与 hooks.cpp 共用，保证「测量」与「绘制」永远一致。
int FontPx(int* f) { return GlyphPx(f); }

// ── Font 颜色统计（正文色 + 阴影色）────────────────────────
// 思路：扫描该 Font 自带 ASCII 字形的像素直方图 —— 出现最多的调色板索引
// 就是正文色，次多且达到阈值的是阴影色。这样自动适配各 UI 元素的配色。
#define COLOR_CACHE_MAX 128
struct ColorCache { int* f; unsigned char body; signed char shadow; };
ColorCache g_cc[COLOR_CACHE_MAX];
int g_ccN = 0;

// render.ini: color=N —— 强制所有中文字形用调色板索引 N 作正文色。
// 缺省 -1 = 自动（按字形直方图取众数）。用于过场文字过暗等个例。
int g_colorOverride = -1;

// render.ini: fontcolor=RVA:NN[;RVA:NN...] —— 只对**指定字体对象**强制正文色。
// RVA = 该 Font 对象相对模块基址的偏移（日志里 "Font %08X" 那个值减 Base()）。
// 也支持关键字 white / bright：white = 取调色板里最亮的一项（通常是纯白）。
// 用于「某块文字过暗/过亮」但不想影响全局的场合。
// 已知：过场诗句用的字体在 RVA 0x28774C（其字形含 112/146/149/113 四个色阶，
//       属于带渐变的描边字体，直方图众数取到最暗的 112 → 中文显得发黑）。
struct FontColorOv { uint32_t rva; int idx; };   // idx: -2 = white
FontColorOv g_fcOv[16];
int g_fcOvN = 0;

// 取 16bpp 调色板里数值最大的一项（= 最亮 = 白）。失败返回 -1。
// ★ 必须跳过索引 255：我们的字形缓冲把 0xFF 当作透明色，
//   若正文色取到 255，blit 会把整个字形当透明跳过 → 文字直接消失。
int BrightestPalEntry() {
    int best = -1;
    __try {
        const uint16_t* pal = *(const uint16_t**)Rva(RVA_FONT_PAL);
        if (pal) {
            unsigned bestv = 0;
            for (int i = 0; i < 255; ++i) {          // 0..254，排除 255
                unsigned v = pal[i];
                if (v >= bestv) { bestv = v; best = i; }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) { best = -1; }
    return best;
}

int FontColorFor(int* f) {
    if (!f || !g_fcOvN) return -1;
    uint32_t rva = (uint32_t)((const uint8_t*)f - Base());
    for (int i = 0; i < g_fcOvN; ++i) {
        if (g_fcOv[i].rva != rva) continue;
        if (g_fcOv[i].idx == -2) return BrightestPalEntry();   // white
        return g_fcOv[i].idx;
    }
    return -1;
}

void FontColors(int* f, unsigned char* body, signed char* shadow) {
    for (int i = 0; i < g_ccN; ++i)
        if (g_cc[i].f == f) { *body = g_cc[i].body; *shadow = g_cc[i].shadow; return; }

    int hist[256];
    memset(hist, 0, sizeof(hist));
    // 「核心像素」直方图：只统计四邻域全是墨的像素。
    // 用于区分「字形主色」与「描边/抗锯齿色」——若某字体的描边像素比主色还多，
    // 直方图众数会取到描边色，中文就会显得过暗/过亮（过场诗句就是这个现象）。
    int core[256];
    memset(core, 0, sizeof(core));
    int b = 0, s = -1, s2 = -1;
    int first = F16(f, font_off::FIRST_CHAR), last = F16(f, font_off::LAST_CHAR);
    unsigned char* info = (unsigned char*)F32(f, font_off::FONT_INFO);
    unsigned char* bmp  = (unsigned char*)F32(f, font_off::FONT_BITMAP);

    if (info && bmp && first <= last && last - first < 4096) {
        for (int ci = first; ; ++ci) {
            unsigned char* fi = info + (ci - first) * 7;
            unsigned char w = fi[1], h = fi[2];
            int32_t off = 0;
            memcpy(&off, fi + 3, 4);
            // 严格边界检查：避免垃圾条目导致越界
            if (w && h && w <= 40 && h <= 48 && off >= 0 && off < 200000) {
                unsigned char* p = bmp + off + 4;
                unsigned tot = (unsigned)w * h;
                // ★ 只有 255 是透明色。0x00 是**正文墨色**（实测 FNT_TBLK 的
                //   'A'/'B'/'g' 位图：笔画像素全是 0x00，周围是 0x92/0x58 等
                //   抗锯齿过渡色）。
                //
                //   ⚠️ 之前一版误把 0 也当透明排除，于是「出现最多的颜色」变成
                //      0x92(146, 浅灰) → 汉字被画成【浅灰正文 + 中灰偏移】，
                //      视觉上就是「重影」。老工程 hook_dll.c 的 font_colors
                //      同样只排除 255，此处与之一致。
                for (unsigned k = 0; k < tot; ++k) {
                    unsigned char v = p[k];
                    if (v != 255) hist[v]++;
                }
                for (unsigned y = 1; y + 1 < h; ++y)
                    for (unsigned x = 1; x + 1 < w; ++x) {
                        unsigned char v = p[y * w + x];
                        if (v == 255) continue;
                        if (p[(y - 1) * w + x] != 255 && p[(y + 1) * w + x] != 255 &&
                            p[y * w + x - 1] != 255 && p[y * w + x + 1] != 255)
                            core[v]++;
                    }
            }
            if (ci == last) break;
        }
    }
    for (int c = 0; c < 256; ++c) if (hist[c] > hist[b]) b = c;
    for (int c = 0; c < 256; ++c)
        if (c != b && hist[c] && (s2 < 0 || hist[c] > hist[s2])) s2 = c;
    if (s2 >= 0 && hist[b] > 0 && hist[s2] >= hist[b] / 20 && hist[s2] >= 20) s = s2;
    if (!g_glyphShadow) s = -1;           // 默认不补阴影（render.ini: shadow=1 可开）
    int bc = 0;
    for (int c = 0; c < 256; ++c) if (core[c] > core[bc]) bc = c;
    if (g_colorOverride >= 0) b = g_colorOverride;   // render.ini: color=N 强制正文色
    int fov = FontColorFor(f);
    if (fov >= 0) b = (unsigned char)fov;            // render.ini: fontcolor=RVA:N 定向覆盖

    if (g_ccN < COLOR_CACHE_MAX) g_cc[g_ccN++] = { f, (unsigned char)b, (signed char)s };
    // 前 8 个字体都记；过场诗句专用字体 (RVA 0x28774C) 无条件记 —— 便于定位配色
    if (g_ccN <= 8 || (uint32_t)((const uint8_t*)f - Base()) == 0x28774C) {
        // 前 4 名按出现次数排序（此前写法有 bug，会把第 1 名重复打印 4 次）
        int top[4] = { -1, -1, -1, -1 };
        for (int c = 0; c < 256; ++c) {
            if (!hist[c]) continue;
            for (int k = 0; k < 4; ++k) {
                if (top[k] < 0 || hist[c] > hist[top[k]]) {
                    for (int m = 3; m > k; --m) top[m] = top[m - 1];
                    top[k] = c;
                    break;
                }
            }
        }
        Log("[i] Font %08X 档位=%dpx 颜色: 正文=%d 阴影=%d 核心峰=%d(%d) | "
            "直方图前四 %d(%d) %d(%d) %d(%d) %d(%d)\r\n",
            (uint32_t)(uintptr_t)f, FontPx(f), b, s, bc, core[bc],
            top[0], top[0] < 0 ? 0 : hist[top[0]],
            top[1], top[1] < 0 ? 0 : hist[top[1]],
            top[2], top[2] < 0 ? 0 : hist[top[2]],
            top[3], top[3] < 0 ? 0 : hist[top[3]]);
    }
    *body = (unsigned char)b;
    *shadow = (signed char)s;
}

// ── 字形位图构建 ────────────────────────────────────────────
// 输出格式与引擎位图一致：{u8 w; u8 0; u8 h; u8 0; u8 pixels[w*h]}
// 像素值 255 = 透明。
struct GlyphBuf {
    uint8_t head[4];
    uint8_t px[44 * 44];
};
GlyphBuf g_glyph;

// 返回字形宽度（= 档位像素），无字形返回 0
int BuildGlyph(int* f, unsigned char lead, unsigned char trail,
               unsigned char body, signed char shadow, int* pxOut) {
    int gi = GlyphIndex(lead, trail);
    if (gi < 0) return 0;
    int px = FontPx(f);
    const unsigned char* m = GlyphMask(gi, px);
    if (!m) return 0;

    int W = m[0], H = m[1];
    if (!W || !H || W > 44 || H > 44) return 0;
    int rowb = (W + 7) >> 3;

    uint8_t* p = g_glyph.px;
    memset(p, 255, (size_t)W * H);
    if (shadow >= 0) {
        for (int y = 0; y < H - 1; ++y)
            for (int x = 0; x < W - 1; ++x)
                if (m[2 + y * rowb + (x >> 3)] & (0x80 >> (x & 7)))
                    p[(y + 1) * W + x + 1] = (uint8_t)shadow;
    }
    for (int y = 0; y < H; ++y)
        for (int x = 0; x < W; ++x)
            if (m[2 + y * rowb + (x >> 3)] & (0x80 >> (x & 7)))
                p[y * W + x] = body;

    g_glyph.head[0] = (uint8_t)W;
    g_glyph.head[1] = 0;
    g_glyph.head[2] = (uint8_t)H;
    g_glyph.head[3] = 0;
    *pxOut = px;
    return px;
}

// 用纯色矩形填一块区域（替代引擎的 blt_buf，避免依赖额外引擎函数）
// ★ sub_403080 不裁剪，所以每块必须先确认整块落在画布内：横向分块填时
//   最后一块天然可能越过 limX 最多 43px，不检查就会写到画布外踩坏堆。
void FillRect(int x1, int y1, int x2, int y2, uint8_t color) {
    if (x2 < x1 || y2 < y1) return;
    int h = y2 - y1 + 1;
    if (h <= 0 || h > 44) return;
    void* buf = ActiveBuf();
    if (!buf) return;
    int cw = ScreenW();
    const int chh = ScreenH();
    if (g_strideClamp) {                       // 同样按 VgaBuf 自己的宽度夹取
        const int pitch = VgaPitch(buf);
        if (pitch > 0) {
            const int sw = pitch / 2;
            if (sw > 16 && sw < cw) cw = sw;
        }
    }
    if (x1 < 0 || y1 < 0) return;
    if (x1 >= cw || y1 >= chh) return;
    // 高度按画布裁剪（只裁尾，避免整块贴底时越界）
    if (y1 + h > chh) h = chh - y1;
    if (h <= 0) return;
    // 位图缓冲只有 44 宽，横向分块填
    for (int x = x1; x <= x2; x += 44) {
        int w = x2 - x + 1;
        if (w > 44) w = 44;
        if (x >= cw) break;
        if (x + w > cw) w = cw - x;          // 最后一块按画布右界裁掉
        if (w <= 0) break;
        memset(g_glyph.px, color, (size_t)w * h);
        g_glyph.head[0] = (uint8_t)w; g_glyph.head[1] = 0;
        g_glyph.head[2] = (uint8_t)h; g_glyph.head[3] = 0;
        PutBmp(buf, x, y1, &g_glyph);
    }
}

// ── 统计 ────────────────────────────────────────────────────
volatile LONG g_putCount = 0;
volatile LONG g_zhCount  = 0;
int*   g_putAddr = nullptr;
void*  g_putOrig = nullptr;
bool   g_putHooked = false;
bool   g_inCjkTest = false;

// ── 原函数入口类型 ──────────────────────────────────────────
// 引擎 Font::put 是 __thiscall（ECX=this，6 个栈参数，ret 0x18）
// 用 8 参数 __fastcall 精确模拟（2 个走寄存器 + 6 个走栈）
FN_PUT g_origPut = nullptr;

inline int CallOrigPut(int* f, int x, int y, const char* s, char cb, int x2, int cap) {
    if (g_putOrig) return ((FN_PUT)g_putOrig)(f, nullptr, x, y, s, cb, x2, cap);
    return x - 1;
}

// ── 绘制一个中文字形；返回推进宽度，0 = 无字形 ──────────────
// 前若干次绘制详细记录，用于核对「画的宽度 vs 进位宽度」是否自洽：
// 若 W > px，说明相邻字会叠在一起（重影）；若 W < px 则字间距偏大。
int DrawGlyph(int* f, int x, int y, unsigned char lead, unsigned char trail) {
    unsigned char body; signed char shadow;
    FontColors(f, &body, &shadow);

    int px = 0;
    int w = BuildGlyph(f, lead, trail, body, shadow, &px);
    if (w <= 0) return 0;

    void* buf = ActiveBuf();
    if (!buf) return w;

    int fh = F16(f, font_off::FONT_HEIGHT);
    int dy = (fh - px) / 2;
    const int py = y + dy;
    const int W = g_glyph.head[0], H = g_glyph.head[2];

    // ★ 引擎的 put_bitmap 不做裁剪 —— 越界绘制会写坏帧缓冲（实测可导致栈被
    //   破坏、EIP/ESP 变成垃圾而崩）。所以必须自己保证矩形整块落在画布内。
    // ★★ 并且上界要用「这块 VgaBuf 自己的宽度」(pitch/2)，不是全局屏宽：
    //   活动缓冲未必等于主屏，画到更小的离屏缓冲上时，按屏宽判定会放行 → 写穿。
    int cw = ScreenW();
    bool committed = true;                     // 拿不到可靠行距时，退回纯逻辑判定
    if (g_strideClamp) {
        const int pitch = VgaPitch(buf);
        // 行距必须可信才用它：偶数、64B(32px) ~ 64KB。否则宁可不用，
        // 免得读到垃圾值把 cw 压成个位数、导致整屏中文消失。
        if (pitch >= 64 && pitch <= 65536 && (pitch & 1) == 0) {
            const int sw = pitch / 2;
            if (sw < cw) cw = sw;
            static LONG pw = 0;
            if (sw != ScreenW() && InterlockedIncrement(&pw) <= 5)
                Log("[i] VgaBuf 画布: pitch=%d -> 宽 %d px（全局屏宽 %d），已按画布夹取\r\n",
                    pitch, sw, ScreenW());
            committed = RectCommitted(VgaPixels(buf), pitch, x, py, x + W - 1, py + H - 1);
        }
    }

    if (x < 0 || py < 0 || x + W > cw || py + H > ScreenH() || !committed) {
        static LONG clampN = 0;
        if (InterlockedIncrement(&clampN) <= 6)
            Log("[!] 绘字越界已跳过: (%d,%d)+%dx%d 画布=%dx%d%s\r\n",
                x, py, W, H, cw, ScreenH(),
                committed ? "" : "  ★目标页未提交 —— 已阻止写穿堆");
        return w;                     // 仍按正常宽度推进，排版不受影响
    }
    PutBmp(buf, x, py, &g_glyph);
    InterlockedIncrement(&g_zhCount);

    static LONG traceN = 0;
    LONG tn = InterlockedIncrement(&traceN);
    if (tn <= 24) {
        int W = g_glyph.head[0], H = g_glyph.head[2];
        // 位图单元格比进位宽是正常的（字身四周留了 1px 边），
        // 真正会重叠的判据是「墨迹宽度 > 进位」。
        int inkX1 = -1;
        for (int y = 0; y < H; ++y)
            for (int x = W - 1; x > inkX1; --x)
                if (g_glyph.px[y * W + x] != 255) { if (x > inkX1) inkX1 = x; break; }
        Log("[dbg] 绘字 #%ld %02X%02X 档=%d 单元格%dx%d 墨迹宽%d 落点(%d,%d) dy=%d "
            "色=%d/%d 进位=%d%s\r\n",
            tn, lead, trail, px, W, H, inkX1 + 1, x, y + dy, dy, (int)body, (int)shadow, w,
            (inkX1 + 1 > w ? "  ★墨迹比进位宽 -> 会重叠" : ""));
    }
    return w;
}

// ── 诊断：调用方地址 + 文本片段 ─────────────────────────────
// 目的：定位「某块文字是引擎哪个函数画出来的」。_ReturnAddress() 取的是
// 引擎 call 我们的那条指令的下一条地址（我们只是 JMP 进来，栈未变），
// 因此可直接在 IDA 里反查调用点。
static volatile uint32_t g_retAddr = 0;

static void Snip(const char* s, char* out, int cap) {
    if (!s) { out[0] = 0; return; }
    int n = 0;
    for (const unsigned char* p = (const unsigned char*)s; *p && n < cap - 5; ++p) {
        if (*p >= 0x20 && *p < 0x7F) out[n++] = (char)*p;
        else {
            out[n++] = '<';
            out[n++] = "0123456789ABCDEF"[*p >> 4];
            out[n++] = "0123456789ABCDEF"[*p & 15];
            out[n++] = '>';
        }
    }
    out[n] = 0;
}

// ── 挂钩实现 ────────────────────────────────────────────────
// 分段策略：ASCII 段转交原函数，中文对自绘。
// 这样英文部分（含空格/国家色/制表/背景清除/鼠标隐藏）100% 走引擎原逻辑。
static int __fastcall Hook_put(int* f, void* edx, int x, int y,
                               const char* str, char clearBack, int x2, int cap) {
    (void)edx;
    InterlockedIncrement(&g_putCount);
    g_retAddr = (uint32_t)(uintptr_t)_ReturnAddress();

    {
        // 精简基线行：无论 debug 级别都记前若干条，保证日志永远有一份脉络
        static LONG tr = 0;
        LONG k = InterlockedIncrement(&tr);
        if (k <= 60 && str) {
            char sn[300];
            Snip(str, sn, 64);
            Log("[dbg] put  #%ld ret=%08X (%d,%d) x2=%d cb=%d zh=%ld \"%s\"\r\n",
                k, g_retAddr, x, y, x2, (int)clearBack, g_zhCount, sn);
        }
    }
    // 深度诊断：完整原始字节 + 逐字字形索引 + 调用栈。
    // frame 取当前 EBP；diag 会先校验它的 +4 处是否等于 retAddr，
    // 不相等（说明编译器做了 FPO，EBP 不是帧指针）就自动跳过回溯，不会打垃圾。
    {
        uint32_t frame = 0;
        __asm { mov frame, ebp }
        DiagText("put", f, str, x, y, x2, x2, (void*)(uintptr_t)g_retAddr, frame);
    }

    if (!f || !str) return CallOrigPut(f, x, y, str, clearBack, x2, cap);

    // ★ 快路径：不含双字节 → 完全交给原函数（英文排版零风险）
    // ★ 崩溃二分：render.ini draw=0 时，中文也整串交回原函数（不自绘）
    if (!HasDBCS(str) || !g_drawEnabled)
        return CallOrigPut(f, x, y, str, clearBack, x2, cap);

    // 规范化右边界（原函数是 x2 = x + maxw*len 再夹到 vgaW-1）。
    // 之前漏了这一步：x2 < 0（= 不限宽）时我们自绘中文完全不设限，
    // 可能画到画布之外 —— 引擎 blitter 不裁剪，会写坏帧缓冲。
    const int scrW = ScreenW();
    int limX = x2;
    if (limX < 0 || limX > scrW - 1) limX = scrW - 1;
    const int fh = F16(f, font_off::FONT_HEIGHT);
    const int spaceW = F16(f, font_off::SPACE_WIDTH);
    const int inter  = F16(f, font_off::INTER_SPACE);
    char seg[256];
    const char* s = str;

    while (*s) {
        unsigned char b = (unsigned char)*s;
        if (!IsPairU(b, (unsigned char)s[1])) {
            // 累积一段 ASCII 并交给原函数
            int n = 0;
            while (*s && n < 250) {
                unsigned char c = (unsigned char)*s;
                if (IsPairU(c, (unsigned char)s[1])) break;
                seg[n++] = *s++;
            }
            seg[n] = 0;
            if (!n) break;

            // 用与引擎等价的宽度定出该段右边界，
            // 否则原函数收尾清屏会把后面的中文擦掉
            int w = MeasureText(f, seg);
            int nx2 = (w > 0) ? x + w - 1 : x;
            if (nx2 > limX) nx2 = limX;
            int r = CallOrigPut(f, x, y, seg, clearBack, nx2, cap);
            // 原函数返回值已含「段尾 inter」，故此处不再补 inter
            x = r + 1;
        } else {
            int w = DrawGlyph(f, x, y, b, (unsigned char)s[1]);
            if (w <= 0) w = spaceW;                     // 缺字 → 按空格推进
            if (x + w > limX) break;
            x += w;
            s += 2;
            x += inter;                                 // 与引擎一致：每字后加 inter
        }
    }

    // 补上尾部背景清除（原函数只在各自段内清）
    if (clearBack && !UseBackBuf() && limX > x)
        FillRect(x, y, limX, y + fh - 1, 0);

    return x - 1;
}

// ══════════════════════════════════════════════════════════════
// Font::put_paragraph @0x4C1480 —— 段落排版 + 中文绘制
// ══════════════════════════════════════════════════════════════
// 为什么必须单独挂钩
// ----------------
// 原函数**自己画字**，不走 Font::put：
//     v14 = info + 7*(byte - first);
//     if (v14[1]) { put_bitmap(active, x, y + v14[0], bitmap + *(DWORD*)(v14+3));
//                   x += v14[1]; }
//     x += inter;
// 中文的 Big5 字节 0xA1-0xF9 落在 [first,last]=[33,255] 内，于是每个字节
// 都被当成一个「单字节字形」从 FNT 里取出 —— FNT 这些槽位是未使用的密集
// 垃圾点阵，一个汉字画两个 → 表现为稠密黑块（用户看到的「乱码」）。
// 换行同因：宽度按单字节累加，与中文真实宽度不符 → 断行错位。
//
// 参数语义（由调用方 sub_4C13A0 / sub_4C1E50 实测确认）
// -----------------------------------------------------
//   a3=x1  a4=y1  a5=x2  a6=y2  a7=串  a8=行距  a9=起始绘制行+1  a10=是否绘制
//   a2(EDX) 与 a3 同值，函数体不使用。
//   ABI: ECX=this, EDX=a2, 栈上 8 个 -> ret 0x20
//   sub_4C1E50 是「只测量不绘制」的循环：反复以 a9=1, a10=0 调用，累加行数，
//   并靠 *(this+1)=next_text 回写继续推进 —— 所以本实现必须同样回写状态，
//   且 a10=0/1 两种模式下的排版结果必须一致。
//
// 策略：纯 ASCII 串直接交原函数（中文以外的排版零回归）；
//       含中文的串自行排版，ASCII 仍用引擎自己的字形（put_bitmap，与原函数
//       逐字节一致），中文用我们的点阵。
constexpr uint32_t RVA_PARA        = 0x0C1480;  // sub_4C1480
constexpr uint32_t RVA_HYPER_COUNT = 0x4D7D78;  // word_8D7D78
constexpr uint32_t RVA_HYPER_ARRAY = 0x4D7D80;  // unk_8D7D80（每项 14 字节）

// 文本控制字节（独立定义，避免与 fontwidth.h 的常量重名）
constexpr unsigned char P_TAB   = 9;
constexpr unsigned char P_LF    = 10;
constexpr unsigned char P_END   = 26;    // TEXT_END
constexpr unsigned char P_SPACE = 32;
constexpr unsigned char P_UNDER = 95;    // '_' 下划线开关
constexpr unsigned char P_TILDE = 126;   // '~' 超链接书签开关

typedef int(__fastcall* FN_PARA)(int*, void*, int, int, int, int, const char*, int, int, char);

volatile LONG g_paraCount = 0;
void*  g_paraOrig = nullptr;

// FontInfo 项：{i8 dy; u8 w; u8 h; i32 off}，7 字节
inline const uint8_t* InfoEntry(int* f, int ch) {
    const uint8_t* info = (const uint8_t*)F32(f, font_off::FONT_INFO);
    if (!info) return nullptr;
    int first = F16(f, font_off::FIRST_CHAR);
    int last  = F16(f, font_off::LAST_CHAR);
    if (ch < first || ch > last) return nullptr;
    return info + 7 * (ch - first);
}

// 单个「单元」的推进宽度与长度（unit = 一个双字节字 / 一个单字节）
inline int UnitWidth(int* f, const char* p, int sp, int px, int* nbytes) {
    unsigned char c = (unsigned char)*p;
    if (IsPairU(c, (unsigned char)p[1])) { *nbytes = 2; return px; }
    *nbytes = 1;
    if (c == P_SPACE) return sp;
    if (c == P_TAB)   return sp * 8;
    if (c >= 0x80 && c <= 0x8F) return 13;          // 国家色条
    const uint8_t* e = InfoEntry(f, c);
    return (e && e[1]) ? e[1] : sp;
}

static int __fastcall Hook_paragraph(int* th, void* edx, int x1, int y1, int x2, int y2,
                                     const char* str, int spacing, int startLine, char draw)
{
    (void)edx;
    InterlockedIncrement(&g_paraCount);
    g_retAddr = (uint32_t)(uintptr_t)_ReturnAddress();
    {
        uint32_t frame = 0;
        __asm { mov frame, ebp }
        DiagText("para", th, str, x1, y1, x2, -1, (void*)(uintptr_t)g_retAddr, frame);
    }

    // 纯 ASCII / 非法入参：完全交给原函数，零回归
    // 崩溃二分：para=0 / draw=0 → 整段交回引擎原函数
    if (!th || !str || !HasDBCS(str) || !g_paraEnabled || !g_drawEnabled)
        return ((FN_PARA)g_paraOrig)(th, nullptr, x1, y1, x2, y2, str, spacing, startLine, draw);

    const int h = F16(th, font_off::FONT_HEIGHT);
    if (!*reinterpret_cast<int8_t*>(th)) return (int)(intptr_t)th;   // 未初始化
    if (y1 + h - 1 > y2) return h;                                   // 与原函数一致

    const int sp    = F16(th, font_off::SPACE_WIDTH);
    const int inter = F16(th, font_off::INTER_SPACE);
    const int px    = GlyphPx(th);
    // 夹到画布内（引擎 blitter 不裁剪，越界会写坏帧缓冲）
    int limX = x2; if (limX < 0 || limX > ScreenW() - 1) limX = ScreenW() - 1;
    int limY = y2; if (limY < 0 || limY > ScreenH() - 1) limY = ScreenH() - 1;
    const uint8_t* bmpBase = (const uint8_t*)F32(th, font_off::FONT_BITMAP);
    void* buf = ActiveBuf();

    WORD* lineCount = (WORD*)((uint8_t*)th + font_off::LINE_COUNT);
    *lineCount = 0;
    WORD* hyCount = (WORD*)Rva(RVA_HYPER_COUNT);
    *hyCount = 0;

    // 超链接书签状态
    bool hyOpen = false;
    int  hyX0 = 0, hyY0 = 0;
    const char* hyPtr = nullptr;
    bool underOpen = false;

    const char* s = str;
    int cx = x1, cy = y1;
    int guard = 0;

    while (*s && *s != (char)P_END && ++guard < 8192) {
        // ── 第一遍：本行能放下到哪里 ──────────────────────────
        const char* p = s;
        int w = 0;
        const char* brkS = nullptr;      // 最近的可断点（空格/制表/中文之后）
        int brkW = 0;
        while (*p && *p != (char)P_END && *p != (char)P_LF) {
            int nb = 0;
            int adv = UnitWidth(th, p, sp, px, &nb);
            if (cx + w + adv - 1 > limX) break;            // 超宽
            // ★ 进位必须与「绘制遍」逐字一致：每字之后都要加 inter_space。
            //   原函数的比较基准 v19 是「含 inter 的游标」：
            //       if (v19 + 宽 - 1 > x2) break;  v19 += 宽;  v19 += inter;
            //   早期版本这里漏了 inter —— 测量认为一行能放 33 字，
            //   实际按 33×(字宽+inter) 画出来就比 x2 宽出「每行字数 × inter」，
            //   表现为中文行尾溢进 UI（简报页约 1.5 个汉字），
            //   而溢出部分不在窗口刷新区内 → 拖动滚动条时留下残影。
            w += adv + inter;
            p += nb;
            // 空格后、制表后、以及中文之后都允许断行
            unsigned char lastc = (unsigned char)p[-1];
            if (nb == 2 || lastc == P_SPACE || lastc == P_TAB) { brkS = p; brkW = w; }
        }
        const char* lineEnd = p;
        // 整行都放得下（或遇到换行/结束）→ 不需按词回退
        if (*p && *p != (char)P_END && *p != (char)P_LF) {
            if (brkS && brkW > 0) { lineEnd = brkS; w = brkW; }
        }
        if (lineEnd == s) {
            // 连一个字都放不下 —— 强制前进，避免死循环
            int nb = 0;
            w = UnitWidth(th, s, sp, px, &nb) + inter;
            lineEnd = s + nb;
        }

        // ── 第二遍：绘制本行 ─────────────────────────────────
        const bool drawThis = (draw != 0) && (*lineCount >= (WORD)(startLine - 1));
        int dx = cx;
        const char* q = s;
        for (; q < lineEnd; ) {
            unsigned char c = (unsigned char)*q;

            if (c == P_UNDER) {                       // 下划线开关（绘制线略，仅维护状态）
                underOpen = !underOpen;
                dx += inter; ++q; continue;
            }
            if (c == P_TILDE) {                       // 超链接书签开关
                if (!hyOpen) {
                    hyOpen = true; hyX0 = dx; hyY0 = cy; hyPtr = q + 1;
                } else {
                    hyOpen = false;
                    // 与原函数一致地登记书签（有界，防止越界写）
                    if (g_hyperEnabled && *hyCount < 40) {
                        uint8_t* e = (uint8_t*)Rva(RVA_HYPER_ARRAY) + 14 * (*hyCount);
                        *(WORD*)(e + 0)  = (WORD)hyX0;
                        *(WORD*)(e + 2)  = (WORD)hyY0;
                        *(WORD*)(e + 4)  = (WORD)dx;
                        *(WORD*)(e + 6)  = (WORD)(cy + h);
                        *(DWORD*)(e + 8) = (DWORD)(uintptr_t)hyPtr;
                        *(WORD*)(e + 12) = (WORD)(int)(q - hyPtr);
                        ++(*hyCount);
                    }
                }
                dx += inter; ++q; continue;
            }
            if (IsPairU(c, (unsigned char)q[1])) {    // 中文：自绘
                if (drawThis && buf) DrawGlyph(th, dx, cy, c, (unsigned char)q[1]);
                dx += px + inter;
                q += 2; continue;
            }
            if (c >= 0x80 && c <= 0x8F) { dx += 13 + inter; ++q; continue; }  // 国家色条：略过
            // 单字节：用引擎自己的字形，与原函数完全一致
            const uint8_t* e = InfoEntry(th, c);
            int nb = 0;
            int adv = UnitWidth(th, q, sp, px, &nb);
            bool isSpaceOrTab = (c == P_SPACE || c == P_TAB);
            if (e && e[1] > 0 && !isSpaceOrTab && drawThis && buf && bmpBase) {
                int32_t off = 0;
                memcpy(&off, e + 3, 4);
                const uint8_t* bm = bmpBase + off;      // 字形位图：+0=W +2=H
                const int gw = bm[0], gh = bm[2];
                const int gy2 = cy + (int)(int8_t)e[0];
                // ★ 与中文自绘同样加画布兜底：引擎的 put_bitmap 不做裁剪，
                //   一旦 dx/gy 越过画布就会踩坏堆（实测堆坏后表现为后续
                //   精灵 RLE 解码读到非法指针而崩溃）。
                if (gw > 0 && gh > 0 && dx >= 0 && gy2 >= 0
                    && dx + gw <= ScreenW() && gy2 + gh <= ScreenH())
                    PutBmp(buf, dx, gy2, (void*)bm);
            }
            dx += adv + inter;
            q += nb;
        }

        // ── 行尾处理 ────────────────────────────────────────
        s = lineEnd;
        while (*s == (char)P_SPACE) ++s;               // 吃掉换行处的空格
        if (!*s || *s == (char)P_END) break;
        if (*s == (char)P_LF) ++s;

        // 与原函数一致：只有「当前行号 >= startLine-1」才推进到下一行
        if (*lineCount >= (WORD)(startLine - 1)) {
            cy += spacing + h;
            if (cy + h - 1 > limY) break;
        }
        cx = x1;
        ++(*lineCount);
    }
    if (underOpen || hyOpen) { /* 未闭合的开关：直接丢弃，与原函数一致（原函数同样不处理） */ }

    // 回写状态（决定调用方能否继续推进 / 排版是否一致）
    *(const char**)((uint8_t*)th + font_off::NEXT_TEXT) = s;
    *(WORD*)((uint8_t*)th + font_off::NEXT_Y) = (WORD)(spacing + cy + h);
    ++(*lineCount);

    static LONG paraTrace = 0;
    LONG pn = InterlockedIncrement(&paraTrace);
    if (pn <= 60) {
        char sn[400];
        Snip(str, sn, 96);
        Log("[dbg] 段落 #%ld ret=%08X x1=%d y1=%d x2=%d y2=%d 行距=%d 起始行=%d 绘制=%d "
            "-> 行数=%d 末y=%d \"%s\"\r\n",
            pn, g_retAddr, x1, y1, x2, y2, spacing, startLine, (int)draw,
            (int)*lineCount, spacing + cy + h, sn);
    }
    return (int)(intptr_t)th;
}

// ══════════════════════════════════════════════════════════════
// Font::put_char @0x4C0FE0 —— 单字绘制（教程提示/逐字绘制路径）
// ══════════════════════════════════════════════════════════════
// ABI（反汇编实证）：ECX=this，栈上 3 个参数 (x, y, u16 textChar) -> ret 0x0C
//   movzx eax,[ebp+10h]        ; textChar（16 位！中文时高字节=Big5 lead）
//   cmp eax,[ecx+15h] / [ecx+17h]  ; 与 first/last 比较（+21 / +23）
//   … info+7*(ch-first)，位图 = bitmap + off，绘制 put_bitmap(active, x, y+dv, bmp)
//
// 它自身不做双字节识别 —— 传入的 textChar 就是完整的 16 位码，所以只要
// textChar>0xFF 且是合法 Big5 对，就直接用我们的点阵画。
//
// 另有一处配套问题：这类逐字绘制路径**按「首字节在 FontInfo 里的宽度」进位**，
// 而 FNT 的 0x81+ 槽位是未使用的垃圾数据（宽度多为 0 或极小）→ 中文只前进
// 一点点，所有字叠在一起（老工程笔记记录的「教程提示叠字」）。因此这里顺带
// 把这些槽位的宽度补成全角宽（这些字节只出现在中文文本里，不影响 ASCII）。
typedef int(__fastcall* FN_PUTCHAR)(int*, void*, int, int, unsigned short);
void* g_putCharOrig = nullptr;
volatile LONG g_putCharCount = 0;

#define DBCS_PATCH_MAX 64
int* g_patchedFont[DBCS_PATCH_MAX];
int  g_patchedN = 0;

void PatchDbcsWidths(int* f) {
    if (!g_dbcsWidthPatch) return;
    for (int i = 0; i < g_patchedN; ++i)
        if (g_patchedFont[i] == f) return;
    if (g_patchedN >= DBCS_PATCH_MAX) return;

    uint8_t* info = (uint8_t*)F32(f, font_off::FONT_INFO);
    int first = F16(f, font_off::FIRST_CHAR);
    int last  = F16(f, font_off::LAST_CHAR);
    if (!info || last < first || last - first > 4095) return;
    if (!InImageRange(info, (size_t)7 * (last - first + 1))) return;
    if (0x81 < first || 0x81 > last) return;

    const uint8_t w = (uint8_t)GlyphPx(f);
    for (int c = 0x81; c <= last; ++c)
        info[7 * (c - first) + 1] = w;
    g_patchedFont[g_patchedN++] = f;
    Log("[i] Font %08X 的 0x81-%02X 槽位宽度已补为 %d（修逐字绘制进位）\r\n",
        (uint32_t)(uintptr_t)f, last, (int)w);
}

static int __fastcall Hook_put_char(int* th, void* edx, int x, int y, unsigned short ch) {
    (void)edx;
    InterlockedIncrement(&g_putCharCount);
    g_retAddr = (uint32_t)(uintptr_t)_ReturnAddress();
    if (ch > 0x80) {
        // put_char 收的是单个 u16 而不是字符串，拼成 2 字节串喂给诊断
        char tmp[3] = { (char)(ch >> 8), (char)(ch & 0xFF), 0 };
        uint32_t frame = 0;
        __asm { mov frame, ebp }
        DiagText("putc", th, tmp, x, y, -1, -1, (void*)(uintptr_t)g_retAddr, frame);
    }
    {
        static LONG tr = 0;
        LONG k = InterlockedIncrement(&tr);
        if (k <= 60)
            Log("[dbg] putc #%ld ret=%08X (%d,%d) ch=%04X %s\r\n",
                k, g_retAddr, x, y, ch, (ch > 0xFF) ? "(双字节)" : "");
    }
    if (!th) return ((FN_PUTCHAR)g_putCharOrig)(th, nullptr, x, y, ch);

    if (ch > 0xFF) {
        unsigned char lead = (unsigned char)(ch >> 8);
        unsigned char trail = (unsigned char)(ch & 0xFF);
        if (IsPairU(lead, trail)) {
            PatchDbcsWidths(th);
            int w = DrawGlyph(th, x, y, lead, trail);
            static LONG t = 0;
            if (InterlockedIncrement(&t) <= 8)
                Log("[dbg] put_char %04X -> 中文自绘 宽=%d @(%d,%d)\r\n", ch, w, x, y);
            return w;
        }
    }
    PatchDbcsWidths(th);
    return ((FN_PUTCHAR)g_putCharOrig)(th, nullptr, x, y, ch);
}

// ══════════════════════════════════════════════════════════════
// 第 4 条文字路径：Font 的逐字节 ASCII 绘制 @0x4C2110 / 0x4C1F40
// ══════════════════════════════════════════════════════════════
// 为什么必须单独挂钩（IDA 交叉引用实证）
// --------------------------------------
// 这两条函数按 `char*` **逐字节**绘制，完全没有双字节概念：
//     v = (ch == ' ') ? font->space_width
//                     : font_info[7*(ch - first_char) + 1];
//     if (x + v <= lim) sub_4C2090(this, surf, stride, x, y, ch);   // 画一个字节
//     x += v + font->inter_space;
//     ++str;
// 中文的 Big5 前导字节 0xA1-0xF9 落在 [first,last] 内 → 一个汉字被当成两个字
// 画出来，就是「鼠标悬浮单位提示」里看到的乱码。
//
// 实证调用点（IDA xrefs_to）：
//   sub_61A4C0 (0x61A5D6) -> sub_4C2110   ← 悬浮提示（名称 + 生命值）
//   sub_450430 (0x4505EE) -> sub_4C2110
//   sub_506840 (0x506C66) -> sub_4C2110
//   null-fn 区 (0x4C224F) -> sub_4C2110
//   null-fn 区 (0x4C207F) -> sub_4C1F40   （0x4C2010 无引用，疑似死代码，仍兜住）
// 这两条是 Font 类里**仅有的**两个不经 Font::put 直接自绘的方法：
// 其余 (0x4C1060 / 0x4C11F0 / 0x4C12C0 / 0x4C2260 / 0x4C2340 / 0x4C2440 / 0x4C2590)
// 全部最终调用 0x4C0AE0，已被 Hook_put 覆盖。
//
// 绘制原语：两条最终都调用 sub_403080(surf, stride, x, y, bmp, pal)
//   —— 16bpp 直接写屏、0xFF 像素视为透明、颜色走 dword_69CFE8 调色板。
//   该位图布局与我们的 g_glyph 完全一致（head={W,0,H,0} + 索引字节 + 255），
//   所以中文点阵可直接喂给它，颜色与英文正文自动一致。
FN_PUT_ASCII    g_putAsciiOrig  = nullptr;   // 0x4C2110 原函数跳板
FN_PUT_ASCII    g_putAscii2Orig = nullptr;   // 0x4C1F40 原函数跳板
FN_PUT_ASCII_CH g_putAsciiChFn  = nullptr;   // 0x4C2090（不挂钩，直呼）
FN_PUT_ASCII_CH g_putAscii2ChFn = nullptr;   // 0x4C1EE0（不挂钩，直呼）
FN_BLIT8        g_blit8         = nullptr;   // 0x403080
volatile LONG   g_putAsciiCount = 0;

// 共用实现：limit = x 轴上界（0x4C2110 用 stride/2，0x4C1F40 用 stride）
static int PutAsciiDBCS(int* f, int surf, int stride, int x, int y, const char* str,
                        int limit, FN_PUT_ASCII_CH putc) {
    const int inter  = F16(f, font_off::INTER_SPACE);
    const int spaceW = F16(f, font_off::SPACE_WIDTH);
    const int last   = F16(f, font_off::LAST_CHAR);
    const int first  = F16(f, font_off::FIRST_CHAR);
    const uint8_t* info = (const uint8_t*)(uintptr_t)F32(f, font_off::FONT_INFO);

    int pal = 0;
    if (g_blit8 && InImageRange(Rva(RVA_FONT_PAL), 4))
        pal = *reinterpret_cast<int*>(Rva(RVA_FONT_PAL));

    unsigned char body; signed char shadow;
    FontColors(f, &body, &shadow);

    // ★★ 逐画布上界：这块 surface 的真实像素宽 = stride/2（引擎自己就是这么算的，
    //   见 sub_4C2110）。之前只拿「全局屏幕宽」当上界，一旦这条路径画到比主屏
    //   小的离屏画布上，检查就会放行 → blit 写穿画布 → 踩坏堆。
    //   clamp=0 可退回旧行为（仅用于对照实验）。
    int cw = ScreenW();
    if (g_strideClamp && stride >= 64 && stride <= 65536 && (stride & 1) == 0) {
        const int sw = stride / 2;
        if (sw < cw) cw = sw;
        static LONG warned = 0;
        if (sw != ScreenW() && InterlockedIncrement(&warned) <= 5)
            Log("[i] puta 画布: stride=%d -> 宽 %d px（全局屏宽 %d），已按画布夹取\r\n",
                stride, sw, ScreenW());
    }

    const char* s = str;
    while (*s) {
        const unsigned char b = (unsigned char)*s;
        if (IsPairU(b, (unsigned char)s[1])) {
            int px = 0;
            int w = BuildGlyph(f, b, (unsigned char)s[1], body, shadow, &px);
            if (w > 0 && g_blit8 && surf) {
                const int fh = F16(f, font_off::FONT_HEIGHT);
                const int gx = x, gy = y + (fh - px) / 2;
                const int W = g_glyph.head[0], H = g_glyph.head[2];
                // ★ 判定基准必须用「进位」(px)，不是「字格宽」(W)。
                //   BuildGlyph 出来的点在格子里左右各留了 1px 边（W = px + 2），
                //   而引擎（以及上面的排版逻辑）都是按 px 进位。
                //   早期版本用 gx + W <= limit 判定，导致每行最后一个字因为
                //   多出的 2px 边被误判越界而**整字丢弃**（日志里的
                //   "[!] puta 越界跳过: x=56 w=15 lim=70"，56+15=71>70）。
                //
                // ★★ 但放宽必须配一把「画布兜底锁」：
                //   sub_403080 完全不做裁剪，写到画布外就是踩堆。实测堆被写坏后
                //   表现为后续任意位置拿到野指针（例如精灵 RLE 解码器读飞
                //   ~500KB 撞到未提交页 → 0xC0000005）。所以这里额外要求整块
                //   字格落在画布内 —— 既不会丢末字，也绝不出画布。
                // ★★★ 最后一道保险：直接问 OS 这块矩形是否落在「已提交」的内存里。
                //   sub_403080 完全不裁剪，而上面的 cw/ScreenH 只是逻辑推断 ——
                //   只要有一次推断错了（离屏画布、stride 异常、坐标被算飞），
                //   写出去就是踩堆。VirtualQuery 能拿到该页的真实提交范围，
                //   只要首尾字节都落在同一个已提交区间内就放行，否则宁可不画。
                // 行距不可信时不做提交页探测（退回纯逻辑判定，避免误杀整屏中文）
                const bool committed = !g_strideClamp || stride < 64 || stride > 65536
                    || RectCommitted((const uint8_t*)(uintptr_t)surf, stride,
                                     gx, gy, gx + W - 1, gy + H - 1);
                if (committed && gx >= 0 && gy >= 0 && W > 0 && H > 0
                    && gx + W <= cw && gy + H <= ScreenH()
                    && gx + px <= limit + 2) {
                    g_blit8(surf, stride, gx, gy, &g_glyph, pal);
                    InterlockedIncrement(&g_zhCount);
                } else {
                    static LONG oc = 0;
                    if (InterlockedIncrement(&oc) <= 6)
                        Log("[!] puta 越界跳过: x=%d 进位=%d 字格=%d lim=%d y=%d cw=%d %s\r\n",
                            gx, px, W, limit, gy, cw,
                            committed ? "(逻辑越界)" : "(★目标页未提交 —— 已阻止写穿堆)");
                }
            }
            if (w <= 0) w = spaceW;             // 缺字 → 按空格推进
            x += w + inter;
            s += 2;
        } else {
            int w;
            if (b == 32) w = spaceW;
            else w = (info && b >= first && b <= last) ? info[7 * (b - first) + 1] : 0;
            // 单字节走引擎自己的绘制函数 —— 它只按 limit 判定、不做画布裁剪，
            // 所以这里同样要用「画布宽」再拦一道。
            if (x + w <= limit && x + w <= cw && putc)
                putc(f, nullptr, surf, stride, x, y, (int)b);
            x += w + inter;
            ++s;
        }
    }
    return (int)(intptr_t)s;
}

static int __fastcall Hook_put_ascii(int* f, void* edx, int surf, int stride,
                                     int x, int y, const char* s) {
    (void)edx;
    InterlockedIncrement(&g_putAsciiCount);
    if (!f || !s || !g_putAsciiOrig) return (x - 1);
    if (!HasDBCS(s) || !g_putAsciiEnabled || !g_drawEnabled)
        return g_putAsciiOrig(f, nullptr, surf, stride, x, y, s);
    {
        static LONG tr = 0;
        if (InterlockedIncrement(&tr) <= 20) {
            uint32_t frame = 0; __asm { mov frame, ebp }
            DiagText("puta", f, s, x, y, -1, -1,
                     (void*)(uintptr_t)_ReturnAddress(), frame);
        }
    }
    return PutAsciiDBCS(f, surf, stride, x, y, s, stride / 2, g_putAsciiChFn);
}

static int __fastcall Hook_put_ascii2(int* f, void* edx, int surf, int stride,
                                      int x, int y, const char* s) {
    (void)edx;
    if (!f || !s || !g_putAscii2Orig) return (x - 1);
    if (!HasDBCS(s) || !g_putAsciiEnabled || !g_drawEnabled)
        return g_putAscii2Orig(f, nullptr, surf, stride, x, y, s);
    return PutAsciiDBCS(f, surf, stride, x, y, s, stride, g_putAscii2ChFn);
}

// ══════════════════════════════════════════════════════════════
// 第 5 条路径：sub_4C1A80 —— 居中多行文本（**只在空格处断行**）
// ══════════════════════════════════════════════════════════════
// 为什么中文会「换行失效 → 被 UI 截断」
// ------------------------------------
// 该函数把文本按 **空格** 切词，逐词测量宽度再决定断行：
//     for (i=0; i<=strlen(Str); ++i) {
//         v23 = Str[i];
//         if (v23 != ' ' && v23) { buf[n++] = v23; }        // 累积一个「词」
//         else { buf[n]=0;
//                if (x1 + text_width(buf) <= x2 || 本行首词) { …记录断点… }
//                else { 在记录的断点处截断、换行 } }
//     }
// 中文没有空格 → 整段被当成**一个词** → 既不换行，又被 x2 右边界硬截断。
// 这就是「人類城鎮是魔族的主」/「立的人類城鎮，用完畢」这类现象的成因。
//
// 对策：调用原函数之前，按 **字符** 边界预先把串重排好 —— 每当累计宽度
// 即将超过 (x2-x1) 就插一个空格。原函数随即在这个空格处断行，于是：
//   • 每行都完整落在 [x1,x2] 内，不再被截断
//   • 断行位置由我们控制（可避开「，。」等行首禁则标点）
//   • 仍复用原函数自己的测量/居中/绘制，排版风格零回归
//
// ABI（反汇编实证）：ECX=this(Font)，栈上 8 个参数 -> ret 0x20
//   入口序言 55 8B EC 6A FF 68 <SEH scope 绝对地址> 64 A1 00 00 00 00 ...
//   ★ 只偷 5 字节（55 8B EC 6A FF），把 push imm32 **留在原处执行** ——
//     否则跳板里的绝对地址不会随 ASLR 重定位，一旦抛异常 SEH 会跳到野地址。
FN_PUT_WRAP  g_wrapOrig = nullptr;
volatile LONG g_wrapCount = 0;

// 行首禁则标点（Big5 码位）——不允许出现在新行的第一个字
static bool NoLineStart(unsigned short c) {
    switch (c) {
    case 0xA141: case 0xA142: case 0xA143: case 0xA144:   // ，、。．
    case 0xA146: case 0xA147: case 0xA148: case 0xA149:   // ；：？！
    case 0xA15E: case 0xA16A: case 0xA16E: case 0xA176:   // ）】》」
    case 0xA17A: case 0xA1A5: case 0xA1A6: case 0xA1A7:   // 』‘’“
    case 0xA1A8:
        return true;
    default:
        return false;
    }
}

static int WrapCharW(int* f, const char* p, int n) {
    unsigned char b = (unsigned char)p[0];
    if (b == 32) return F16(f, font_off::SPACE_WIDTH);
    if (n >= 2 && IsPairU(b, (unsigned char)p[1])) return FontPx(f);
    const uint8_t* info = (const uint8_t*)(uintptr_t)F32(f, font_off::FONT_INFO);
    int first = F16(f, font_off::FIRST_CHAR), last = F16(f, font_off::LAST_CHAR);
    if (info && b >= first && b <= last) return info[7 * (b - first) + 1];
    return 0;
}

static int __fastcall Hook_putwrap(int* f, void* edx, int x1, int y1, int x2, int y2,
                                   const char* str, int lead, int draw, int size) {
    (void)edx;
    InterlockedIncrement(&g_wrapCount);
    if (!f || !str || !g_wrapOrig) return 0;
    // 崩溃二分：wrap=0 / draw=0 → 完全不接管，交给引擎原逻辑
    if (!HasDBCS(str) || !g_wrapEnabled || !g_drawEnabled)
        return g_wrapOrig(f, nullptr, x1, y1, x2, y2, str, lead, draw, size);

    const int maxW = x2 - x1;
    if (maxW < 24)                                  // 宽度不合理：交给原函数
        return g_wrapOrig(f, nullptr, x1, y1, x2, y2, str, lead, draw, size);

    char buf[4096];
    int n = 0;
    const int spaceW = F16(f, font_off::SPACE_WIDTH);
    int lineW = 0;
    const char* p = str;
    while (*p && n < (int)sizeof(buf) - 8) {
        unsigned char b = (unsigned char)*p;
        if (b == 32) { buf[n++] = ' '; lineW += spaceW; ++p; continue; }
        int len = IsPairU(b, (unsigned char)p[1]) ? 2 : 1;
        int w = WrapCharW(f, p, len);
        if (lineW > 0 && lineW + w > maxW - spaceW) {
            unsigned short code = (len == 2)
                ? (unsigned short)((b << 8) | (unsigned char)p[1]) : 0;
            if (!NoLineStart(code)) { buf[n++] = ' '; lineW = 0; }
        }
        buf[n++] = p[0];
        if (len == 2) buf[n++] = p[1];
        lineW += w;
        p += len;
    }
    buf[n] = 0;

    static LONG lg = 0;
    if (InterlockedIncrement(&lg) <= 10) {
        char sn[300];
        Snip(buf, sn, 200);
        Log("[i] 预换行 maxW=%d 末行宽%d: \"%s\"\r\n", maxW, lineW, sn);
    }
    return g_wrapOrig(f, nullptr, x1, y1, x2, y2, buf, lead, draw, size);
}

}  // namespace

namespace sk2 {

long PutCallCount()  { return (long)g_putCount; }
long CjkGlyphCount() { return (long)g_zhCount; }

// 读取 <exe目录>\update\<name> 的内容（纯文本，最多 256 字节）
static bool ReadCfg(const char* name, char* out, int cap) {
    char path[MAX_PATH] = {};
    GetModuleFileNameA(nullptr, path, MAX_PATH);
    char* slash = strrchr(path, '\\');
    if (slash) slash[1] = 0; else path[0] = 0;
    lstrcatA(path, "update\\");
    lstrcatA(path, name);
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return false;
    DWORD r = 0;
    ReadFile(h, out, (DWORD)cap - 1, &r, nullptr);
    out[r] = 0;
    CloseHandle(h);
    return true;
}

// ---------------------------------------------------------------------------
// OEM 转换表的恒等化
//
// 引擎加载部分资源时会就地做一次 cp437(OEM) -> Latin-1 变换：
//
//   void oem_convert(char* buf, int len)        // 0x5B8FC0, __cdecl
//   {
//       for (char* p = buf; len > 0 && *p; --len, ++p)
//           if ((unsigned char)*p >= 0x80 && T[*p] != 0x3F)
//               *p = (char)T[*p];               // T 基址 = 0x681028
//   }
//
// 表的 256 项按字节值索引，但前 128 项所在位置其实是别的数据，
// 真正有效的部分从 +0x80 开始（RVA 0x2810A8）。
//
// 这张表会打乱我们写进资源里的 Big5 码：例如「練」= BD 6D，
// T[BD]=A2 之后变成 A2 6D，正好落进 g_stdCode 的某个槽位，
// 于是显示成完全无关的「賄」。这就是教学关「魔族訓練一」变成
// 「□族訓賄□」的根因。
//
// 对策：把表的有效部分改成恒等映射 T[b] = b，于是所有资源统一以
// 「原始 Big5」为线上格式 —— 与那些本来就不走这张表的 .res 一致。
// ---------------------------------------------------------------------------
static int g_oemIdentity = 1;
static int g_exeStrPatch = 1;      // render.ini: exestr=0 可关掉 exe 标签本地化

static void ApplyOemIdentity() {
    if (!g_oemIdentity) {
        Log("[i] OEM 表恒等化：已跳过 (render.ini oem=0)\r\n");
        return;
    }
    // 表基址：索引 b 的地址 = Base() + 0x281028 + b；有效段从 b=0x80 起
    uint8_t* t = (uint8_t*)Rva(0x281028 + 0x80);
    if (!InImageRange(t, 128)) {
        Log("[X] OEM 表地址越界，未修补\r\n");
        return;
    }
    // 指纹校验：确认这确实是 cp437->Latin-1 表，避免改错东西
    if (!(t[0x80 - 0x80] == 0xC7 && t[0x81 - 0x80] == 0xFC &&
          t[0x82 - 0x80] == 0xE9 && t[0x9F - 0x80] == 0x83)) {
        Log("[X] OEM 表指纹不符 (C7 FC E9 .. 83)，未修补: "
            "%02X %02X %02X\r\n", t[0], t[1], t[2]);
        return;
    }
    DWORD oldProt = 0;
    if (!VirtualProtect(t, 128, PAGE_READWRITE, &oldProt)) {
        Log("[X] OEM 表所在页不可写，未修补 (GLE=%lu)\r\n", GetLastError());
        return;
    }
    int changed = 0;
    for (int i = 0; i < 128; ++i) {
        uint8_t want = (uint8_t)(0x80 + i);
        if (t[i] != want) { t[i] = want; ++changed; }
    }
    VirtualProtect(t, 128, oldProt, &oldProt);
    Log("[O] OEM 表已恒等化 (RVA %08X, %d/128 字节改写)\r\n",
        0x281028 + 0x80, changed);
}

// 解析 update\render.ini：
//     size=13|16|24      字号档位（缺省自动）
//     shadow=0|1         中文是否加 1px 偏移阴影（缺省 1）
// 兼容旧的 update\fontsize.txt（单行数字）
static void LoadRenderCfg() {
    char buf[257] = {};
    if (ReadCfg("render.ini", buf, sizeof(buf))) {
        const char* p = strstr(buf, "size=");
        if (p) {
            int v = atoi(p + 5);
            if (v == 13 || v == 16 || v == 24) {
                g_glyphPxOverride = v;
                Log("[i] render.ini: size=%d\r\n", v);
            }
        }
        p = strstr(buf, "shadow=");
        if (p) {
            int v = atoi(p + 7);
            g_glyphShadow = (v != 0);
            Log("[i] render.ini: shadow=%d\r\n", g_glyphShadow ? 1 : 0);
        }
        p = strstr(buf, "dbcs_width=");
        if (p) {
            int v = atoi(p + 11);
            g_dbcsWidthPatch = (v != 0);
            Log("[i] render.ini: dbcs_width=%d\r\n", g_dbcsWidthPatch ? 1 : 0);
        }
        // ── 崩溃二分开关：关掉某条自绘路径，其余不变 ──
        // 用法：update\render.ini 里写 draw=0 / puta=0 / wrap=0 / para=0 / hyp=0
        // 目的是把「是不是我们自绘写坏了内存」定位到具体某一条路径。
        static const struct { const char* key; bool* flag; const char* desc; } SW[] = {
            { "draw=",  &g_drawEnabled,     "Font::put/段落/逐字节 中文自绘" },
            { "puta=",  &g_putAsciiEnabled, "逐字节路径 0x4C2110/0x4C1F40" },
            { "wrap=",  &g_wrapEnabled,     "居中多行换行 0x4C1A80" },
            { "para=",  &g_paraEnabled,     "put_paragraph 中文排版" },
            { "hyp=",   &g_hyperEnabled,    "段落超链接数组写入" },
            { "clamp=", &g_strideClamp,     "逐画布(stride/2)边界兜底" },
        };
        for (const auto& s : SW) {
            p = strstr(buf, s.key);
            if (p) {
                int v = atoi(p + strlen(s.key));
                *s.flag = (v != 0);
                Log("[i] render.ini: %s%d  (%s)\r\n", s.key, v ? 1 : 0,
                    v ? "启用" : "★已关闭（中文不由此路径绘制）");
            }
        }
        p = strstr(buf, "oem=");
        if (p) {
            int v = atoi(p + 4);
            g_oemIdentity = (v != 0);
            Log("[i] render.ini: oem=%d  %s\r\n", g_oemIdentity,
                g_oemIdentity ? "(恒等化，资源统一为原始 Big5)"
                              : "(保留引擎 OEM→Latin1 变换)");
        }
        p = strstr(buf, "debug=");
        if (p) {
            int v = atoi(p + 6);
            if (v < 0) v = 0;
            if (v > 3) v = 3;
            DiagInit(v);
            Log("[i] render.ini: debug=%d  %s\r\n", v,
                v == 0 ? "(仅计数)"
                : v == 1 ? "(只详记可疑串)"
                : v == 2 ? "(详记所有含中文的串)"
                         : "(连纯 ASCII 也记，日志会很大)");
        }
        p = strstr(buf, "color=");
        if (p) {
            int v = atoi(p + 6);
            if (v >= 0 && v <= 255) {
                g_colorOverride = v;
                Log("[i] render.ini: color=%d（强制中文正文色）\r\n", v);
            }
        }
        p = strstr(buf, "exestr=");
        if (p) {
            g_exeStrPatch = (atoi(p + 7) != 0);
            Log("[i] render.ini: exestr=%d  %s\r\n", g_exeStrPatch,
                g_exeStrPatch ? "(本地化 exe 内置 UI 标签)" : "(保留英文标签)");
        }
        // fontcolor=RVA十六进制:值[;RVA:值...]  值 = 0-255 索引，或 white
        // 例：fontcolor=28774C:white
        p = strstr(buf, "fontcolor=");
        if (p) {
            const char* q = p + 10;
            while (*q && g_fcOvN < 16) {
                char* end = nullptr;
                unsigned long rva = strtoul(q, &end, 16);
                if (end && *end == ':') {
                    const char* v = end + 1;
                    int idx;
                    if ((v[0] == 'w' || v[0] == 'W') && (v[1] == 'h' || v[1] == 'H') &&
                        (v[2] == 'i' || v[2] == 'I') && (v[3] == 't' || v[3] == 'T') &&
                        (v[4] == 'e' || v[4] == 'E')) {
                        idx = -2;                       // 特殊值：调色板最亮项（白）
                    } else {
                        idx = atoi(v);
                    }
                    if (idx == -2 || (idx >= 0 && idx <= 255)) {
                        g_fcOv[g_fcOvN].rva = (uint32_t)rva;
                        g_fcOv[g_fcOvN].idx = idx;
                        ++g_fcOvN;
                        Log("[i] render.ini: fontcolor RVA %06X -> %s\r\n", (unsigned)rva,
                            idx == -2 ? "white(最亮调色板项)" : "");
                    }
                    q = end + 1;
                }
                while (*q && *q != ';' && *q != '\r' && *q != '\n') ++q;
                if (*q != ';') break;
                ++q;
            }
            Log("[i] render.ini: fontcolor 定向配色 %d 条\r\n", g_fcOvN);
        }
        return;
    }
    if (ReadCfg("fontsize.txt", buf, sizeof(buf))) {
        int v = atoi(buf);
        if (v == 13 || v == 16 || v == 24) {
            g_glyphPxOverride = v;
            Log("[i] 字号档位被 update\\fontsize.txt 覆盖为 %d\r\n", v);
        }
    }
}

bool InstallPut() {
    LoadRenderCfg();
    ApplyOemIdentity();

    g_putAddr = (int*)FindInText(SIG_PUT, SIG_PUT_LEN);
    if (!g_putAddr) {
        Log("[X] Font::put 签名未命中\r\n");
        return false;
    }
    if (!InImageRange((void*)g_putAddr, 0x200)) {
        Log("[X] put 地址越界\r\n");
        return false;
    }
    Log("[i] Font::put @ %08X\r\n", (uint32_t)(uintptr_t)g_putAddr);
    Log("[i] put 的 ABI 栈参数应为 6 个 (ret 0x18)，实测前 16 字节:\r\n");
    LogBytes("      bytes", g_putAddr, 16);

    // 跳板（偷 6 字节：push ebp; mov ebp,esp; sub esp,24h）
    g_putOrig = BuildTrampoline(g_putAddr, 6);
    if (!g_putOrig) {
        Log("[X] put 跳板创建失败\r\n");
        return false;
    }

    if (!InstallJump(g_putAddr, (void*)&Hook_put, nullptr)) {
        Log("[X] put 安装 JMP 失败\r\n");
        return false;
    }
    g_putHooked = true;
    Log("[O] Font::put 已挂钩（纯 ASCII 串仍走原函数）\r\n");
    return true;
}

long PutGlyphCount() { return (long)g_zhCount; }
long ParagraphCallCount() { return (long)g_paraCount; }
long PutCharCallCount()  { return (long)g_putCharCount; }

bool InstallPutChar() {
    void* addr = (void*)Rva(RVA_PUT_CHAR);
    // 签名（反汇编实证）：55 8B EC 83 EC 08 89 4D FC 0F B7 45 10
    static const uint8_t SIG[] = { 0x55,0x8B,0xEC,0x83,0xEC,0x08,0x89,0x4D,0xFC,0x0F,0xB7,0x45,0x10 };
    if (memcmp(addr, SIG, sizeof(SIG)) != 0) {
        Log("[!] put_char @ %08X 字节特征不符，未挂钩（教程提示可能仍有叠字）\r\n",
            0x400000u + RVA_PUT_CHAR);
        return false;
    }
    g_putCharOrig = BuildTrampoline(addr, 6);      // 偷 push ebp; mov ebp,esp; sub esp,8
    if (!g_putCharOrig) {
        Log("[X] put_char 跳板创建失败\r\n");
        return false;
    }
    if (!InstallJump(addr, (void*)&Hook_put_char, nullptr)) {
        Log("[X] put_char 安装 JMP 失败\r\n");
        return false;
    }
    Log("[O] Font::put_char @ %08X 已挂钩\r\n", 0x400000u + RVA_PUT_CHAR);
    return true;
}

// 第 4 条文字路径：Font 的逐字节 ASCII 绘制（悬浮工具提示、部分 HUD）
bool InstallPutAscii() {
    // 先绑定底层绘制原语（不挂钩，直接调用）
    {
        const uint8_t* b = (const uint8_t*)Rva(RVA_BLIT8);
        if (!InImageRange(b, 0x40) || b[0] != 0x55 || b[1] != 0x8B || b[2] != 0xEC) {
            Log("[!] 底层 blit @ %08X 特征不符，第 4 条路径未挂钩\r\n",
                0x400000u + RVA_BLIT8);
            return false;
        }
        g_blit8         = (FN_BLIT8)Rva(RVA_BLIT8);
        g_putAsciiChFn  = (FN_PUT_ASCII_CH)Rva(RVA_PUT_ASCII_CH);
        g_putAscii2ChFn = (FN_PUT_ASCII_CH)Rva(RVA_PUT_ASCII2_CH);
    }

    // 两条包装函数序言均为 55 8B EC 83 EC 18（push ebp; mov ebp,esp; sub esp,18h）
    static const uint8_t SIG[] = { 0x55,0x8B,0xEC,0x83,0xEC,0x18 };
    int ok = 0;
    struct { uint32_t rva; void** orig; void* hook; const char* name; } jobs[] = {
        { RVA_PUT_ASCII,  (void**)&g_putAsciiOrig,  (void*)&Hook_put_ascii,  "0x4C2110" },
        { RVA_PUT_ASCII2, (void**)&g_putAscii2Orig, (void*)&Hook_put_ascii2, "0x4C1F40" },
    };
    for (auto& j : jobs) {
        void* addr = Rva(j.rva);
        if (!InImageRange(addr, 0x100) || memcmp(addr, SIG, sizeof(SIG)) != 0) {
            Log("[!] %s 序言不符，未挂钩\r\n", j.name);
            continue;
        }
        void* tramp = BuildTrampoline(addr, 6);
        if (!tramp) { Log("[X] %s 跳板创建失败\r\n", j.name); continue; }
        if (!InstallJump(addr, j.hook, nullptr)) {
            Log("[X] %s 安装 JMP 失败\r\n", j.name); continue;
        }
        *j.orig = tramp;
        ++ok;
        Log("[O] Font 逐字节绘制 @ %08X (%s) 已挂钩（中文自绘）\r\n",
            0x400000u + j.rva, j.name);
    }
    return ok > 0;
}

// 第 5 条路径：居中多行文本自动换行（sub_4C1A80）
bool InstallTextWrap() {
    void* addr = Rva(RVA_PUT_WRAP);
    static const uint8_t SIG[] = { 0x55, 0x8B, 0xEC, 0x6A, 0xFF, 0x68 };
    if (!InImageRange(addr, 0x400) || memcmp(addr, SIG, sizeof(SIG)) != 0) {
        Log("[!] 居中多行文本 @ %08X 序言不符，未挂钩（超宽中文不会自动换行）\r\n",
            0x400000u + RVA_PUT_WRAP);
        return false;
    }
    // 只偷 5 字节，SEH 的 push imm32 留在原处执行（避免 ASLR 重定位问题）
    g_wrapOrig = (FN_PUT_WRAP)BuildTrampoline(addr, 5);
    if (!g_wrapOrig) { Log("[X] 文本换行跳板创建失败\r\n"); return false; }
    if (!InstallJump(addr, (void*)&Hook_putwrap, nullptr)) {
        Log("[X] 文本换行安装 JMP 失败\r\n"); return false;
    }
    Log("[O] 居中多行文本 @ %08X 已挂钩（中文按字断行，修 UI 截断）\r\n",
        0x400000u + RVA_PUT_WRAP);
    return true;
}

// ── exe 内置 UI 标签的运行时本地化 ──────────────────────────
// 这些标签位于 exe 的字符串区（VA 0x663A24 起），每个串以 NUL 结尾，
// 前后各有 4 字节事件码（PRDY/PRDN/PREI/…）。中文 Big5 比英文短，
// 可原地覆盖 + 补零，**不改动磁盘上的原版文件**。
// 位置来源：PE 段表换算 —— .rdata RVA 0x25A000 / raw 0x258A00，
//           文件偏移 = VA - 0x400000 - 0x25A000 + 0x258A00。
struct ExeLabel {
    uint32_t va;               // 目标字符串 VA（IDA 视角）
    const char* en;            // 原英文（用作指纹校验）
    const unsigned char* zh;   // Big5 字节（不含 NUL）
    int zhLen;
    int cap;                   // = 原串长 + 1（含 NUL），可用空间
};

static const unsigned char EL_SMALL[]  = {0xA4,0x70};                                   // 小
static const unsigned char EL_LARGE[]  = {0xA4,0x6A};                                   // 大
static const unsigned char EL_SELECT[] = {0xBF,0xEF,0xBE,0xDC};                         // 選擇
static const unsigned char EL_CHGDSP[] = {0xA7,0xF3,0xA7,0xEF,0xC5,0xE3,0xA5,0xDC,0xBC,0xD2,0xA6,0xA1};  // 更改顯示模式
static const unsigned char EL_FULLSC[] = {0xA5,0xFE,0xBF,0xC3,0xB9,0xF5,0xBC,0xD2,0xA6,0xA1};            // 全螢幕模式
static const unsigned char EL_WINDOW[] = {0xB5,0xF8,0xB5,0xA1,0xBC,0xD2,0xA6,0xA1};                      // 視窗模式
static const unsigned char EL_DIPLO[]  = {0xA5,0x7E,0xA5,0xE6,0xBD,0xD0,0xA8,0x44};                      // 外交請求
static const unsigned char EL_NORMAL[] = {0xA5,0xBF,0xB1,0x60};                                          // 正常
static const unsigned char EL_AUTOP[]  = {0xA6,0xDB,0xB0,0xCA,0xB4,0xA3,0xA5,0xDC,0xB7,0xF9,0xA4,0xCD};  // 自動提示盟友
static const unsigned char EL_CEASE[]  = {0xB0,0xB1,0xA4,0xF5};                                          // 停火

static const ExeLabel kExeLabels[] = {
    { 0x663A24, "Small",  EL_SMALL,  sizeof(EL_SMALL),  6 },
    { 0x663A34, "Large",  EL_LARGE,  sizeof(EL_LARGE),  6 },
    { 0x663A44, "Select", EL_SELECT, sizeof(EL_SELECT), 7 },
    { 0x663A54, "Change Display Mode", EL_CHGDSP, sizeof(EL_CHGDSP), 20 },
    { 0x663A68, "Full Screen Mode",    EL_FULLSC, sizeof(EL_FULLSC), 17 },
    { 0x663A84, "Windowed Mode",       EL_WINDOW, sizeof(EL_WINDOW), 14 },
    { 0x663A9C, "Diplomatic Requests", EL_DIPLO,  sizeof(EL_DIPLO),  20 },
    { 0x663AC8, "Normal",  EL_NORMAL, sizeof(EL_NORMAL), 7 },
    { 0x663AD0, "Auto Prompt for Allies", EL_AUTOP, sizeof(EL_AUTOP), 23 },
    { 0x663AF0, "Above and Cease Fire",   EL_CEASE, sizeof(EL_CEASE), 21 },
};

void PatchExeStrings() {
    if (!g_exeStrPatch) {
        Log("[i] exe 标签本地化：已跳过 (render.ini exestr=0)\r\n");
        return;
    }
    int ok = 0, skip = 0;
    for (const ExeLabel& e : kExeLabels) {
        uint8_t* p = (uint8_t*)Rva(e.va - 0x400000u);
        const int enLen = (int)strlen(e.en);
        if (!InImageRange(p, (size_t)e.cap) || enLen + 1 > e.cap) { ++skip; continue; }
        if (memcmp(p, e.en, (size_t)enLen + 1) != 0) {      // 连同 NUL 一起校验
            Log("[!] exe 标签指纹不符 @ %08X（%s），跳过\r\n", e.va, e.en);
            ++skip;
            continue;
        }
        if (e.zhLen + 1 > e.cap) { ++skip; continue; }
        DWORD old = 0;
        if (!VirtualProtect(p, (SIZE_T)e.cap, PAGE_READWRITE, &old)) { ++skip; continue; }
        memcpy(p, e.zh, (size_t)e.zhLen);
        memset(p + e.zhLen, 0, (size_t)(e.cap - e.zhLen));
        VirtualProtect(p, (SIZE_T)e.cap, old, &old);
        ++ok;
    }
    Log("[O] exe 内置 UI 标签已本地化：%d 条（跳过 %d，指纹/空间不符）\r\n", ok, skip);
}

bool InstallParagraph() {
    void* addr = FindInText(SIG_PUT_PARAGRAPH, SIG_PUT_PARAGRAPH_LEN);
    if (!addr) {
        Log("[X] put_paragraph 签名未命中\r\n");
        return false;
    }
    if (!InImageRange(addr, 0x640)) {
        Log("[X] put_paragraph 地址越界\r\n");
        return false;
    }
    Log("[i] Font::put_paragraph @ %08X\r\n", (uint32_t)(uintptr_t)addr);

    // ABI 校验：函数体末尾必须是 C2 20 00（ret 0x20，8 个栈参数）。
    // 找不到就不挂钩 —— 约定不匹配的 JMP 会直接崩栈。
    {
        const uint8_t* b = (const uint8_t*)addr;
        bool retOk = false;
        for (int i = 0; i + 3 <= 0x640; ++i)
            if (b[i] == 0xC2 && b[i + 1] == 0x20 && b[i + 2] == 0x00) { retOk = true; break; }
        if (!retOk) {
            Log("[X] ABI 校验失败：未在函数体内找到 ret 0x20，放弃挂钩\r\n");
            return false;
        }
    }

    g_paraOrig = BuildTrampoline(addr, 6);      // 偷 push ebp; mov ebp,esp; sub esp,30h
    if (!g_paraOrig) {
        Log("[X] put_paragraph 跳板创建失败\r\n");
        return false;
    }
    if (!InstallJump(addr, (void*)&Hook_paragraph, nullptr)) {
        Log("[X] put_paragraph 安装 JMP 失败\r\n");
        return false;
    }
    Log("[O] Font::put_paragraph 已挂钩（纯 ASCII 段落仍走原函数）\r\n");
    return true;
}

// ── 离线自测 ────────────────────────────────────────────────
void CjkSelfTest() {
    Log("\r\n--- CJK 字形自测 ---\r\n");

    struct C { const char* label; unsigned char lead, trail; int wantGlyph; };
    const C cs[] = {
        { "確 BD54", 0xBD, 0x54, 1 },
        { "中 A4A4", 0xA4, 0xA4, 1 },
        { "文 A4E5", 0xA4, 0xE5, 1 },
        { "字 A6r",  0xA6, 0x72, 1 },
        { "custom 90-40", 0x90, 0x40, 1 },
        { "非法 20-20", 0x20, 0x20, 0 },   // 非 Big5 对
    };
    int pass = 0, fail = 0;
    for (const auto& c : cs) {
        int gi = GlyphIndex(c.lead, c.trail);
        bool ok = (c.wantGlyph ? gi >= 0 : gi < 0);
        ok ? ++pass : ++fail;
        Log("[%s] %-14s 字形索引 = %d%s\r\n", ok ? "O" : "X", c.label, gi,
            (gi >= N_CHARS) ? "  (来源: 补充表)" : "");

        if (gi >= 0) {
            // 检查三档点阵都能构建出有墨迹的位图
            for (int px = 0; px < 3; ++px) {
                int size = (px == 0 ? 13 : (px == 1 ? 16 : 24));
                const unsigned char* m = GlyphMask(gi, size);
                if (!m) { Log("[X]   %dpx 掩码为空\r\n", size); ++fail; continue; }
                int W = m[0], H = m[1], rowb = (W + 7) >> 3;
                int ink = 0;
                for (int y = 0; y < H; ++y)
                    for (int x = 0; x < W; ++x)
                        if (m[2 + y * rowb + (x >> 3)] & (0x80 >> (x & 7))) ++ink;
                Log("[%s]   %2dpx  %dx%d  墨点 %d\r\n",
                    ink > 0 ? "O" : "X", size, W, H, ink);
                if (ink <= 0) ++fail;
            }
        }
    }
    Log("[i] 自测结果: %d 通过, %d 失败\r\n", pass, fail);
    Log("[i] 字形池: 13px=%d B, 16px=%d B, 24px=%d B, 主表 %d + 补充 %d = %d 个字形\r\n",
        (int)sizeof(gpool13), (int)sizeof(gpool16), (int)sizeof(gpool24), N_CHARS, EXTRA_N,
        N_CHARS + EXTRA_N);
}

}  // namespace sk2
