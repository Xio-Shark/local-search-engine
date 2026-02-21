package com.localengine.scoring;

import com.localengine.config.Constants;

public class BM25Scorer {
    private final int totalDocs;
    private final double avgDocLength;
    private final double k1;
    private final double b;

    public BM25Scorer(int totalDocs, double avgDocLength) {
        this(totalDocs, avgDocLength, Constants.BM25_K1, Constants.BM25_B);
    }

    public BM25Scorer(int totalDocs, double avgDocLength, double k1, double b) {
        this.totalDocs = Math.max(totalDocs, 1);
        this.avgDocLength = avgDocLength <= 0 ? 1.0 : avgDocLength;
        this.k1 = k1;
        this.b = b;
    }

    public double computeIDF(int docFrequency) {
        int boundedDf = Math.max(0, Math.min(docFrequency, totalDocs));
        return Math.log((totalDocs - boundedDf + 0.5) / (boundedDf + 0.5) + 1);
    }

    public double score(int termFrequency, int docFrequency, int docLength) {
        return score(termFrequency, docFrequency, docLength, totalDocs, avgDocLength);
    }

    public double score(int termFrequency, int docFrequency, int docLength, int dynamicTotalDocs, double dynamicAvgDocLength) {
        if (termFrequency <= 0) {
            return 0.0;
        }
        int safeTotalDocs = Math.max(dynamicTotalDocs, 1);
        double safeAvgDocLength = dynamicAvgDocLength <= 0 ? 1.0 : dynamicAvgDocLength;
        int boundedDf = Math.max(0, Math.min(docFrequency, safeTotalDocs));
        double idf = Math.log((safeTotalDocs - boundedDf + 0.5) / (boundedDf + 0.5) + 1);
        double normalizedDocLength = Math.max(docLength, 0);
        double norm = 1 - b + b * (normalizedDocLength / safeAvgDocLength);
        return idf * (termFrequency * (k1 + 1)) / (termFrequency + k1 * norm);
    }

    public double scoreMultiTerms(int[] termFrequencies, int[] docFrequencies, int docLength) {
        if (termFrequencies == null || docFrequencies == null) {
            throw new IllegalArgumentException("词频数组不能为null");
        }
        if (termFrequencies.length != docFrequencies.length) {
            throw new IllegalArgumentException("词频数组长度不一致");
        }
        double totalScore = 0;
        for (int index = 0; index < termFrequencies.length; index++) {
            totalScore += score(termFrequencies[index], docFrequencies[index], docLength);
        }
        return totalScore;
    }
}
