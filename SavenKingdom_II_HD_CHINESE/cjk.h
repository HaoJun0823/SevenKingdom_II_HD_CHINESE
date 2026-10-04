// cjk.h — 中文渲染：字形索引、点阵构建、Font::put 挂钩
#pragma once
#include <cstdint>

namespace sk2 {

bool InstallPut();        // Stage 3：挂钩 Font::put，中文自绘
bool InstallParagraph();  // Stage 3：挂钩 Font::put_paragraph，段落排版 + 中文自绘
bool InstallPutChar();    // Stage 3：挂钩 Font::put_char，单字绘制路径 + 宽度补丁
bool InstallPutAscii();   // Stage 3：挂钩 Font 的逐字节 ASCII 绘制（工具提示等第 4 条路径）
bool InstallTextWrap();   // Stage 3：挂钩居中多行文本，按字断行（修 UI 截断）
void PatchExeStrings();   // Stage 3：运行时本地化 exe 内置 UI 标签（不改原文件）
void CjkSelfTest();       // 离线自测：验证字形索引与点阵构建
long PutCallCount();      // put 被调用次数
long ParagraphCallCount();// put_paragraph 被调用次数
long PutCharCallCount();  // put_char 被调用次数
long CjkGlyphCount();     // 实际绘制过的中文字形数
long VqCount();           // VirtualQuery 实际调用次数（提交页探测，按画布缓存后应远小于字形数）
int  MeasureText(int* font, const char* s);   // 用引擎语义测量串宽

// 字形索引：Big5/自定义双字节 -> 字形池下标，<0 表示这个字没有形状。
// 诊断模块 diag.cpp 用它来区分「字库缺口」与「字节错位」这两类乱码。
int  GlyphIndex(int lead, int trail);

// ── 逐路径耗时统计（render.ini: perf=1 开启，缺省开）──────────
// 目的：把「按按钮卡一下」定性到具体哪条路径，而不是靠猜。
// 每次 hook 进出各读一次高精度计数器，累加到对应槽位，
// 监控行（每 5 秒）打印 次数/累计毫秒/单次微秒。
enum {
    PERF_TW = 0,    // text_width（测量，引擎最热函数）
    PERF_PUT,       // Font::put
    PERF_PARA,      // Font::put_paragraph
    PERF_PUTC,      // Font::put_char
    PERF_PUTA,      // 逐字节 ASCII 路径 0x4C2110 / 0x4C1F40
    PERF_WRAP,      // 居中多行文本
    PERF_GLYPH,     // 单个中文字形自绘（含 BuildGlyph + put_bitmap）
    PERF_FILL,      // 尾部背景清除 FillRect
    PERF_DIAG,      // 乱码诊断 DiagText
    PERF_LOG,       // 日志写入 Log/LogRaw
    PERF_N
};
void           PerfBegin(int id);            // 与 PerfEnd 配对
void           PerfEnd(int id);
long           PerfCount(int id);
double         PerfMs(int id);               // 累计毫秒
void           PerfReport(char* out, int cap);   // 生成一段多行报告
extern int     g_perfEnabled;

}  // namespace sk2
