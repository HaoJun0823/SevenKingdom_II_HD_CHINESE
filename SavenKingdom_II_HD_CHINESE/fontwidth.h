// fontwidth.h — 双字节宽度计算（方案 B 核心）
//
// 引擎 FontInfo 查表原式（IDA 实证 sub_4C0780）：
//     width = *(uint8*)(font_info + 7*(ch - first_char) + 1);
// 即「码位 -> FontInfo 索引 -> 取 width」。这是索引即地址的映射。
//
// 本方案不改动引擎代码，而是构造一份「等效 FontInfo 池」：
//   对每个 Big5 lead 字节 0xA1-0xF9 与自定义 0x90-0xA0，
//   在对应索引处填 width=全宽，从而让引擎按原逻辑推进。
//
// 但引擎取字符是 v14 = *(uint8*)Stra（单字节），
// 双字节的 trail 会被当作下一个字符 -> 必须让 trail 落在 FontInfo 表的空白项。
// 解决办法见 hooks.cpp 的字符迭代接管。
#pragma once

#include <cstdint>

namespace sk2 {

// 引擎中「双字节 lead」的判定范围
constexpr int B5_LEAD_MIN = 0xA1;
constexpr int B5_LEAD_MAX = 0xF9;
constexpr int CUST_LEAD_MIN = 0x90;
constexpr int CUST_LEAD_MAX = 0xA0;

// Big5 trail 合法区间
constexpr bool IsTrailValid(int t) {
    return (t >= 0x40 && t <= 0x7E) || (t >= 0xA1 && t <= 0xFE);
}

// 是否构成一个双字节字符对
inline bool IsDBCSPair(int lead, int trail) {
    bool leadOk = (lead >= B5_LEAD_MIN && lead <= B5_LEAD_MAX) ||
                  (lead >= CUST_LEAD_MIN && lead <= CUST_LEAD_MAX);
    return leadOk && IsTrailValid(trail);
}

// trail 计算列索引（与引擎 big5idx/custidx 一致）
inline int TrailIndex(int trail) {
    if (trail >= 0x40 && trail <= 0x7E) return trail - 0x40;
    if (trail >= 0xA1 && trail <= 0xFE) return 63 + (trail - 0xA1);
    return -1;
}

// 国家颜色码：0x80-0x8F，引擎按 13px 固定宽度绘制
inline bool IsNationColor(int c) { return c >= 0x80 && c <= 0x8F; }

// 控制字符
constexpr int CHAR_TAB   = 9;
constexpr int CHAR_SPACE = 32;
constexpr int CHAR_TILDE = 126;   // '~' 引擎当超链接标记 *问题根源
constexpr int CHAR_UNDER = 95;    // '_' 下划线
constexpr int CHAR_LF    = 10;
constexpr int CHAR_END   = 26;    // 0x1A TEXT_END

// -- 字形库（由 fontdata.h 提供，外部生成）--------------------
// 声明在 fontdata.h 中（自动生成），这里只声明查询入口
int  GlyphIndex(int lead, int trail);   // 返回字形序号，-1 = 无
const uint8_t* GlyphMask(int gi, int px);

// -- 宽度计算（与引擎语义对齐，但支持双字节）------------------
// fontHeight 用于判定点阵档位：<16 -> 13px, <24 -> 16px, else 24px
int DBCSWidth(int lead, int trail, int fontHeight);

}  // namespace sk2
