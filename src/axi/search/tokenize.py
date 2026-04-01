"""中英文混合分词：jieba 分词 + 工具名符号拆分。"""

import logging
import re

import jieba

jieba.setLogLevel(logging.WARNING)


def _is_cjk_char(ch: str) -> bool:
    """判断字符是否为 CJK 统一汉字。"""
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF) or (0x3400 <= cp <= 0x4DBF)


def _keep_token(token: str) -> bool:
    """保留多字符 token 或单字 CJK token，过滤单字符 ASCII 噪声。"""
    s = token.strip()
    if not s:
        return False
    return len(s) > 1 or _is_cjk_char(s[0])


def preprocess(text: str) -> str:
    """预处理文本，返回空格分隔的 token 串（供 bm25s 二次分词）。

    1. 将下划线/连字符/斜杠替换为空格（拆开工具名）
    2. jieba 分词（自动处理中英文混合）
    3. 小写化，过滤无意义的单字符 ASCII token（保留单字 CJK）
    """
    text = re.sub(r"[/_\-]", " ", text)
    tokens = jieba.cut(text)
    return " ".join(t.lower() for t in tokens if _keep_token(t))
