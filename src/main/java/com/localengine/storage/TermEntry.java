package com.localengine.storage;

/**
 * 词典词条，记录词项到倒排与位置文件偏移的映射。
 */
public record TermEntry(String term, int docFreq, long postingsOffset, long positionsOffset) {
}
