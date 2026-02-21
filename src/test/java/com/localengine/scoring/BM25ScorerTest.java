package com.localengine.scoring;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.DisplayName;

import static org.junit.jupiter.api.Assertions.*;

/**
 * BM25评分器测试
 */
class BM25ScorerTest {

    @Test
    @DisplayName("计算IDF：文档频率越低，IDF越高")
    void testComputeIDF() {
        BM25Scorer scorer = new BM25Scorer(1000, 100.0);
        
        // df=1（稀有词），IDF应该很高
        double idfRare = scorer.computeIDF(1);
        // df=500（常见词），IDF应该较低
        double idfCommon = scorer.computeIDF(500);
        
        assertTrue(idfRare > idfCommon, "稀有词的IDF应该高于常见词");
        assertTrue(idfRare > 0, "IDF应该为正数");
        assertTrue(idfCommon > 0, "IDF应该为正数");
    }

    @Test
    @DisplayName("计算BM25分数：基础功能测试")
    void testScore() {
        BM25Scorer scorer = new BM25Scorer(100, 50.0);
        
        // tf=5, df=10, docLength=50
        double score = scorer.score(5, 10, 50);
        
        assertTrue(score > 0, "分数应该为正数");
    }

    @Test
    @DisplayName("词频越高，分数越高（其他条件相同）")
    void testScoreIncreasesWithTF() {
        BM25Scorer scorer = new BM25Scorer(100, 50.0);
        
        double scoreLowTF = scorer.score(1, 10, 50);
        double scoreHighTF = scorer.score(10, 10, 50);
        
        assertTrue(scoreHighTF > scoreLowTF, "词频越高，分数应该越高");
    }

    @Test
    @DisplayName("文档越短，分数越高（词频相同）")
    void testScoreHigherForShorterDoc() {
        BM25Scorer scorer = new BM25Scorer(100, 100.0);
        
        double scoreLongDoc = scorer.score(5, 10, 200);  // 比平均值长
        double scoreShortDoc = scorer.score(5, 10, 50);  // 比平均值短
        
        assertTrue(scoreShortDoc > scoreLongDoc, "短文档应该有更高分数");
    }

    @Test
    @DisplayName("多个词项累计评分")
    void testScoreMultiTerms() {
        BM25Scorer scorer = new BM25Scorer(100, 50.0);
        
        int[] tfs = {5, 3, 2};
        int[] dfs = {10, 20, 30};
        
        double score = scorer.scoreMultiTerms(tfs, dfs, 50);
        
        assertTrue(score > 0, "累计分数应该为正数");
        
        // 验证累计效果
        double singleTermScore = scorer.score(5, 10, 50);
        assertTrue(score > singleTermScore, "多个词项的分数应该高于单个词项");
    }

    @Test
    @DisplayName("自定义BM25参数")
    void testCustomBM25Parameters() {
        // k1=2.0, b=0.5
        BM25Scorer customScorer = new BM25Scorer(100, 50.0, 2.0, 0.5);
        BM25Scorer defaultScorer = new BM25Scorer(100, 50.0);
        
        double customScore = customScorer.score(5, 10, 100);
        double defaultScore = defaultScorer.score(5, 10, 100);
        
        // 参数不同，分数应该不同
        assertNotEquals(customScore, defaultScore, "自定义参数应该产生不同分数");
    }

    @Test
    @DisplayName("零词频应该返回零分")
    void testZeroTFReturnsZero() {
        BM25Scorer scorer = new BM25Scorer(100, 50.0);
        
        double score = scorer.score(0, 10, 50);
        
        assertEquals(0.0, score, "词频为0时应该返回零分");
    }

    @Test
    @DisplayName("文档频率等于总文档数时的IDF")
    void testIDFWhenDFEqualsTotalDocs() {
        BM25Scorer scorer = new BM25Scorer(100, 50.0);
        
        // df = N（所有文档都包含该词）
        double idf = scorer.computeIDF(100);
        
        assertTrue(idf > 0, "即使所有文档都包含该词，IDF也应该为正数");
    }
}
