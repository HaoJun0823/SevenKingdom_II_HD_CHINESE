// diag.h — 乱码诊断（Stage 3 辅助）
//
// 为什么需要单独一个模块
// ----------------------
// 乱码的成因有四类，只看截图完全无法区分：
//   ① 字形缺失 —— 字节对正确，但字库里没有这个形状
//   ② 字节错位 —— 读取起点偏了，整串双字节对全部错开
//   ③ 未挂钩路径 —— 某条我们没覆盖的绘制路径按单字节处理
//   ④ 资源本身写坏 —— 翻译工具写入时破坏了相邻字段
//
// 本模块把每次文本绘制的**原始字节、逐字字形索引、调用栈**落盘，
// 使得「这段乱码到底是什么」可以纯靠日志判读，不必依赖截图。
//
// 开关：update\render.ini 里写 debug=N
//   0  关闭（默认）            仅累计计数
//   1  只详记可疑串            缺字形 / trail 非法 / 控制符 / 宽度溢出
//   2  详记所有含中文的串      推荐档（已做去重，日志量可控）
//   3  连纯 ASCII 串也记       日志很大，仅在怀疑英文路径出问题用
#pragma once
#include <cstdint>

namespace sk2 {

void DiagInit(int level);
int  DiagLevel();

// 记录一次文本绘制。无关的量填 -1 即可。
//   kind       "put" / "para" / "putc"
//   fontObj    Font 对象地址（用于区分不同字号与配色的 UI 元素）
//   str        待绘字符串（必须以 NUL 结尾）
//   endX       实际结束横坐标，用于判「宽度算爆」，无关时 -1
//   retAddr    _ReturnAddress()，引擎调用点的下一条指令
//   frame      调用方的 EBP 值（用于回溯调用栈），填 0 则跳过回溯
void DiagText(const char* kind, const void* fontObj, const char* str,
              int x, int y, int x2, int endX, void* retAddr, uint32_t frame);

// 启动后台线程，周期性把「累计查不到的字形」刷到日志。
// 目的是即使游戏崩溃（来不及走 DLL_PROCESS_DETACH）也能留下证据。
void DiagStartFlusher();

// 立即输出缺字形汇总表
void DiagDumpMissing();

// 把 cp950(引擎内部 Big5 变体) 字节流转成 UTF-8 追加到 d，供日志直接读中文。
void AppendCp950Utf8(char* d, int cap, int* used, const unsigned char* s, int len);

}
