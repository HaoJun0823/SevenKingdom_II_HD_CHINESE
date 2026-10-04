// hooks.h — 各阶段挂钩实现
#pragma once
#include <cstdint>

namespace sk2 {

bool InstallTextWidth();   // Stage 2
bool InstallFontInfo();    // Stage 3
void SelfTest();           // 离线自测：不依赖游戏资源验证双字节宽度
long TextWidthCallCount(); // text_width 被调用的累计次数
int  MeasureText(int* font, const char* s);  // 按引擎语义测量串宽（优先用原函数）

}  // namespace sk2
