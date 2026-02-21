package com.localengine.storage;

import java.util.Arrays;

/**
 * 倒排列表，包含文档ID与对应词频。
 *
 * @param docIds 递增文档ID数组
 * @param termFreqs 与docIds同长度的词频数组
 */
public record PostingList(int[] docIds, int[] termFreqs) {
    /**
     * 构造时执行防御性校验并复制输入数据，避免外部修改。
     */
    public PostingList {
        if (docIds == null || termFreqs == null) {
            throw new IllegalArgumentException("docIds与termFreqs不能为null");
        }
        if (docIds.length != termFreqs.length) {
            throw new IllegalArgumentException("docIds与termFreqs长度不一致: " + docIds.length + " vs " + termFreqs.length);
        }
        for (int index = 0; index < docIds.length; index++) {
            if (docIds[index] < 0) {
                throw new IllegalArgumentException("docId不能为负数，位置=" + index + ", value=" + docIds[index]);
            }
            if (termFreqs[index] < 0) {
                throw new IllegalArgumentException("termFreq不能为负数，位置=" + index + ", value=" + termFreqs[index]);
            }
            if (index > 0 && docIds[index] <= docIds[index - 1]) {
                throw new IllegalArgumentException("docIds必须严格递增，位置=" + index + ", current=" + docIds[index]);
            }
        }
        docIds = Arrays.copyOf(docIds, docIds.length);
        termFreqs = Arrays.copyOf(termFreqs, termFreqs.length);
    }

    /**
     * 返回倒排项数量。
     *
     * @return 倒排项数量
     */
    public int size() {
        return docIds.length;
    }

    /**
     * 获取指定位置的文档ID。
     *
     * @param index 倒排项下标
     * @return 文档ID
     */
    public int docId(int index) {
        return docIds[index];
    }

    /**
     * 获取指定位置的词频。
     *
     * @param index 倒排项下标
     * @return 词频
     */
    public int termFreq(int index) {
        return termFreqs[index];
    }

    @Override
    public int[] docIds() {
        return Arrays.copyOf(docIds, docIds.length);
    }

    @Override
    public int[] termFreqs() {
        return Arrays.copyOf(termFreqs, termFreqs.length);
    }
}
