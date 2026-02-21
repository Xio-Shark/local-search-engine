package com.localengine.text;

import java.util.List;

public interface Tokenizer {

    /**
     * 将输入文本切分为词项列表。
     */
    List<Token> tokenize(String text);
}
