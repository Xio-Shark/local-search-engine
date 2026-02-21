package com.localengine.query;

import com.localengine.config.Constants;
import com.localengine.config.EngineConfig;
import com.localengine.document.DocType;
import com.localengine.document.Document;
import com.localengine.document.DocumentTable;
import com.localengine.highlight.Snippet;
import com.localengine.highlight.SnippetGenerator;
import com.localengine.index.DiskSegment;
import com.localengine.index.IndexManager;
import com.localengine.scoring.BM25Scorer;
import com.localengine.storage.PostingList;
import com.localengine.storage.TermEntry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.io.IOException;
import java.nio.file.Files;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;

public class QueryEngine {
    private static final Logger logger = LoggerFactory.getLogger(QueryEngine.class);
    
    private final IndexManager indexManager;
    private final DocumentTable docTable;
    private final BM25Scorer scorer;
    private final SnippetGenerator snippetGenerator;

    /**
     * 使用默认 BM25 参数构造查询引擎。
     */
    public QueryEngine(IndexManager indexManager, DocumentTable docTable) {
        this(indexManager, docTable, Constants.BM25_K1, Constants.BM25_B);
    }

    /**
     * 使用 EngineConfig 注入 BM25 参数构造查询引擎。
     */
    public QueryEngine(IndexManager indexManager, DocumentTable docTable, EngineConfig config) {
        this(indexManager, docTable, config.getBm25K1(), config.getBm25B());
    }

    private QueryEngine(IndexManager indexManager, DocumentTable docTable, double k1, double b) {
        this.indexManager = indexManager;
        this.docTable = docTable;
        this.scorer = new BM25Scorer(docTable.getTotalDocCount(), docTable.getAverageDocLength(), k1, b);
        this.snippetGenerator = new SnippetGenerator();
    }

    public SearchResult search(String queryString, int limit) throws IOException {
        long startNanos = System.nanoTime();
        String normalizedQuery = normalizeDirectFileNameQuery(queryString);
        QueryParser.ParseResult parseResult = new QueryParser().parse(normalizedQuery);
        QueryNode ast = parseResult.ast();
        QueryNode.SortDirective sortDirective = parseResult.sort();

        int liveDocCount = Math.max(docTable.getTotalDocCount(), 1);
        double avgDocLength = Math.max(docTable.getAverageDocLength(), 1.0);
        Set<String> queryTerms = extractQueryTerms(ast);
        List<DiskSegment> activeSegments = indexManager.getActiveSegments();
        Map<String, Integer> globalDocFreq = buildGlobalDocFrequency(activeSegments, queryTerms);

        Map<Integer, Double> mergedScores = new HashMap<>();
        for (DiskSegment segment : activeSegments) {
            Set<Integer> segmentDocIds = filterLiveDocIds(segment.getAllDocIds());
            Map<Integer, Double> segmentScores = evaluateNode(ast, segment, segmentDocIds, globalDocFreq, liveDocCount, avgDocLength);
            mergeScores(mergedScores, segmentScores);
        }

        // 根据 SortDirective 决定排序逻辑
        List<Map.Entry<Integer, Double>> sortedHits;
        if (sortDirective != null) {
            sortedHits = sortByField(mergedScores, sortDirective.field(), limit);
        } else {
            sortedHits = mergedScores.entrySet().stream()
                .sorted((left, right) -> Double.compare(right.getValue(), left.getValue()))
                .limit(Math.max(limit, 0))
                .toList();
        }

        List<SearchHit> hits = new ArrayList<>(sortedHits.size());
        for (Map.Entry<Integer, Double> hit : sortedHits) {
            Document document = docTable.findById(hit.getKey())
                .orElseThrow(() -> new IOException("文档不存在: docId=" + hit.getKey()));
            String content = readContentQuietly(document.path());
            List<Snippet> snippets = snippetGenerator.generate(content, queryTerms, List.of());
            hits.add(new SearchHit(document, hit.getValue(), snippets));
        }

        long elapsedMs = (System.nanoTime() - startNanos) / 1_000_000;
        return new SearchResult(hits, mergedScores.size(), elapsedMs, queryString);
    }

    private String normalizeDirectFileNameQuery(String queryString) {
        if (queryString == null) {
            return "";
        }
        String trimmedQuery = queryString.trim();
        if (trimmedQuery.isEmpty()) {
            return trimmedQuery;
        }
        if (trimmedQuery.contains(":")
            || trimmedQuery.contains(" ")
            || trimmedQuery.contains("\t")
            || trimmedQuery.contains("\"")
            || trimmedQuery.contains("(")
            || trimmedQuery.contains(")")
            || trimmedQuery.contains("*")
            || trimmedQuery.contains("/")
            || trimmedQuery.contains("\\")
            || trimmedQuery.startsWith("-")) {
            return trimmedQuery;
        }
        if (!trimmedQuery.contains(".")) {
            return trimmedQuery;
        }
        return "filename:" + trimmedQuery;
    }

    /**
     * 根据字段排序搜索结果。
     * 支持 mtime（按修改时间降序）和 size（按文件大小降序）。
     */
    private List<Map.Entry<Integer, Double>> sortByField(
            Map<Integer, Double> scores, String field, int limit) {
        // 预取所有命中文档，避免排序时重复查 DB
        Map<Integer, Document> docCache = new HashMap<>(scores.size());
        for (Integer docId : scores.keySet()) {
            docTable.findById(docId).ifPresent(doc -> docCache.put(docId, doc));
        }

        Comparator<Map.Entry<Integer, Double>> comparator = (a, b) -> {
            Document docA = docCache.get(a.getKey());
            Document docB = docCache.get(b.getKey());
            if (docA == null || docB == null) {
                return 0;
            }
            return switch (field) {
                case "mtime" -> docB.mtime().compareTo(docA.mtime());
                case "size" -> Long.compare(docB.sizeBytes(), docA.sizeBytes());
                default -> Double.compare(b.getValue(), a.getValue());
            };
        };
        return scores.entrySet().stream()
            .sorted(comparator)
            .limit(Math.max(limit, 0))
            .toList();
    }

    private Map<Integer, Double> evaluateNode(
            QueryNode node,
            DiskSegment segment,
            Set<Integer> segmentDocIds,
            Map<String, Integer> globalDocFreq,
            int totalDocs,
            double avgDocLength) throws IOException {
        if (node instanceof QueryNode.TermQuery termQuery) {
            return evaluateTerm(termQuery.term(), segment, globalDocFreq, totalDocs, avgDocLength);
        }
        if (node instanceof QueryNode.PrefixQuery prefixQuery) {
            return evaluatePrefix(prefixQuery.prefix(), segment, globalDocFreq, totalDocs, avgDocLength);
        }
        if (node instanceof QueryNode.PhraseQuery phraseQuery) {
            return evaluatePhrase(phraseQuery.terms(), segment, globalDocFreq, totalDocs, avgDocLength);
        }
        if (node instanceof QueryNode.FieldQuery fieldQuery) {
            return evaluateField(fieldQuery, segment, segmentDocIds);
        }
        if (node instanceof QueryNode.RangeQuery rangeQuery) {
            return evaluateRange(rangeQuery, segment, segmentDocIds);
        }
        if (node instanceof QueryNode.NotQuery notQuery) {
            Map<Integer, Double> child = evaluateNode(notQuery.child(), segment, segmentDocIds, globalDocFreq, totalDocs, avgDocLength);
            Map<Integer, Double> result = new HashMap<>();
            for (Integer docId : segmentDocIds) {
                if (!child.containsKey(docId)) {
                    result.put(docId, 0.0);
                }
            }
            return result;
        }
        if (node instanceof QueryNode.BooleanQuery booleanQuery) {
            Map<Integer, Double> left = evaluateNode(booleanQuery.left(), segment, segmentDocIds, globalDocFreq, totalDocs, avgDocLength);
            Map<Integer, Double> right = evaluateNode(booleanQuery.right(), segment, segmentDocIds, globalDocFreq, totalDocs, avgDocLength);
            if (booleanQuery.op() == QueryNode.BoolOp.AND) {
                Map<Integer, Double> result = new HashMap<>();
                for (Map.Entry<Integer, Double> leftEntry : left.entrySet()) {
                    Double rightScore = right.get(leftEntry.getKey());
                    if (rightScore != null) {
                        result.put(leftEntry.getKey(), leftEntry.getValue() + rightScore);
                    }
                }
                return result;
            }
            Map<Integer, Double> result = new HashMap<>(left);
            mergeScores(result, right);
            return result;
        }
        return Map.of();
    }

    private Map<Integer, Double> evaluateTerm(
            String term,
            DiskSegment segment,
            Map<String, Integer> globalDocFreq,
            int totalDocs,
            double avgDocLength) throws IOException {
        String normalizedTerm = term == null ? "" : term.toLowerCase(Locale.ROOT);
        if (normalizedTerm.isBlank()) {
            return Map.of();
        }

        PostingList postingList = segment.getPostings(normalizedTerm);
        if (postingList == null) {
            return Map.of();
        }
        int docFreq = globalDocFreq.getOrDefault(normalizedTerm, segment.getDocFreq(normalizedTerm));
        if (docFreq <= 0) {
            return Map.of();
        }
        int[] docIds = postingList.docIds();
        int[] termFreqs = postingList.termFreqs();
        Map<Integer, Double> scores = new HashMap<>();
        for (int index = 0; index < docIds.length; index++) {
            Document document = docTable.findById(docIds[index]).orElse(null);
            if (document == null) {
                continue;
            }
            double score = scorer.score(termFreqs[index], docFreq, document.tokenCount(), totalDocs, avgDocLength);
            scores.put(docIds[index], score);
        }
        return scores;
    }

    private Map<Integer, Double> evaluatePrefix(
            String prefix,
            DiskSegment segment,
            Map<String, Integer> globalDocFreq,
            int totalDocs,
            double avgDocLength) throws IOException {
        String normalizedPrefix = prefix == null ? "" : prefix.toLowerCase(Locale.ROOT);
        if (normalizedPrefix.isBlank()) {
            return Map.of();
        }
        Map<Integer, Double> scores = new HashMap<>();
        for (TermEntry entry : segment.prefixSearch(normalizedPrefix)) {
            mergeScores(scores, evaluateTerm(entry.term(), segment, globalDocFreq, totalDocs, avgDocLength));
        }
        return scores;
    }

    private Map<Integer, Double> evaluatePhrase(
            List<String> terms,
            DiskSegment segment,
            Map<String, Integer> globalDocFreq,
            int totalDocs,
            double avgDocLength) throws IOException {
        if (terms == null || terms.isEmpty()) {
            return Map.of();
        }
        
        // 预计算所有term的评分，避免重复读取
        Map<String, Map<Integer, Double>> termScoresCache = new HashMap<>();
        Map<Integer, Double> firstTermScores = null;
        
        for (String term : terms) {
            String normalizedTerm = term == null ? "" : term.toLowerCase(Locale.ROOT);
            if (normalizedTerm.isBlank()) {
                continue;
            }
            Map<Integer, Double> scores = evaluateTerm(normalizedTerm, segment, globalDocFreq, totalDocs, avgDocLength);
            termScoresCache.put(normalizedTerm, scores);
            if (firstTermScores == null) {
                firstTermScores = scores;
            }
        }
        
        if (firstTermScores == null || firstTermScores.isEmpty()) {
            return Map.of();
        }

        Map<Integer, Double> phraseScores = new HashMap<>();
        for (Map.Entry<Integer, Double> entry : firstTermScores.entrySet()) {
            int docId = entry.getKey();
            if (matchesPhraseInDoc(terms, segment, docId)) {
                double score = 0.0;
                for (String term : terms) {
                    String normalizedTerm = term == null ? "" : term.toLowerCase(Locale.ROOT);
                    if (normalizedTerm.isBlank()) {
                        continue;
                    }
                    score += termScoresCache.getOrDefault(normalizedTerm, Map.of()).getOrDefault(docId, 0.0);
                }
                phraseScores.put(docId, score);
            }
        }
        return phraseScores;
    }

    private boolean matchesPhraseInDoc(List<String> terms, DiskSegment segment, int docId) throws IOException {
        List<int[]> positionsByTerm = new ArrayList<>(terms.size());
        for (String term : terms) {
            String normalizedTerm = term == null ? "" : term.toLowerCase(Locale.ROOT);
            if (normalizedTerm.isBlank()) {
                return false;
            }
            int[] positions = segment.getPositionsForDoc(normalizedTerm, docId);
            if (positions.length == 0) {
                return false;
            }
            positionsByTerm.add(positions);
        }

        Set<Integer> nextExpected = new HashSet<>();
        for (int startPos : positionsByTerm.getFirst()) {
            nextExpected.add(startPos + 1);
        }

        for (int index = 1; index < positionsByTerm.size(); index++) {
            Set<Integer> currentExpected = new HashSet<>();
            for (int pos : positionsByTerm.get(index)) {
                if (nextExpected.contains(pos)) {
                    currentExpected.add(pos + 1);
                }
            }
            if (currentExpected.isEmpty()) {
                return false;
            }
            nextExpected = currentExpected;
        }
        return true;
    }

    private Map<Integer, Double> evaluateField(QueryNode.FieldQuery fieldQuery, DiskSegment segment, Set<Integer> segmentDocIds) {
        List<Integer> candidateDocIds;
        if ("path".equals(fieldQuery.field())) {
            candidateDocIds = docTable.findDocIdsByPathPrefix(fieldQuery.value());
        } else if ("ext".equals(fieldQuery.field())) {
            candidateDocIds = docTable.findDocIdsByExtension(fieldQuery.value());
        } else if ("filename".equals(fieldQuery.field()) || "name".equals(fieldQuery.field())) {
            candidateDocIds = docTable.findDocIdsByFileName(fieldQuery.value());
        } else if ("type".equals(fieldQuery.field())) {
            try {
                candidateDocIds = docTable.findDocIdsByType(DocType.valueOf(fieldQuery.value().toUpperCase()));
            } catch (IllegalArgumentException exception) {
                return Map.of();
            }
        } else {
            return Map.of();
        }

        Map<Integer, Double> result = new HashMap<>();
        for (Integer docId : candidateDocIds) {
            if (segmentDocIds.contains(docId) && !segment.isDeleted(docId)) {
                result.put(docId, 1.0);
            }
        }
        return result;
    }

    private Map<Integer, Double> evaluateRange(QueryNode.RangeQuery rangeQuery, DiskSegment segment, Set<Integer> segmentDocIds) {
        List<Integer> candidateDocIds;
        try {
            if ("size".equals(rangeQuery.field())) {
                long min = Long.parseLong(rangeQuery.from());
                long max = Long.parseLong(rangeQuery.to());
                candidateDocIds = docTable.findDocIdsBySizeRange(min, max);
            } else if ("mtime".equals(rangeQuery.field())) {
                Instant from = Instant.parse(rangeQuery.from());
                Instant to = Instant.parse(rangeQuery.to());
                candidateDocIds = docTable.findDocIdsByMtimeRange(from, to);
            } else {
                return Map.of();
            }
        } catch (RuntimeException exception) {
            return Map.of();
        }

        Map<Integer, Double> result = new HashMap<>();
        for (Integer docId : candidateDocIds) {
            if (segmentDocIds.contains(docId) && !segment.isDeleted(docId)) {
                result.put(docId, 1.0);
            }
        }
        return result;
    }


    private Set<String> extractQueryTerms(QueryNode node) {
        Set<String> terms = new HashSet<>();
        collectTerms(node, terms);
        return terms;
    }

    private void collectTerms(QueryNode node, Set<String> terms) {
        if (node instanceof QueryNode.TermQuery termQuery) {
            terms.add(termQuery.term().toLowerCase(Locale.ROOT));
            return;
        }
        if (node instanceof QueryNode.PrefixQuery prefixQuery) {
            terms.add(prefixQuery.prefix().toLowerCase(Locale.ROOT));
            return;
        }
        if (node instanceof QueryNode.PhraseQuery phraseQuery) {
            for (String term : phraseQuery.terms()) {
                terms.add(term.toLowerCase(Locale.ROOT));
            }
            return;
        }
        if (node instanceof QueryNode.BooleanQuery booleanQuery) {
            collectTerms(booleanQuery.left(), terms);
            collectTerms(booleanQuery.right(), terms);
            return;
        }
        if (node instanceof QueryNode.NotQuery notQuery) {
            collectTerms(notQuery.child(), terms);
        }
    }

    private void mergeScores(Map<Integer, Double> target, Map<Integer, Double> source) {
        for (Map.Entry<Integer, Double> entry : source.entrySet()) {
            target.merge(entry.getKey(), entry.getValue(), Double::sum);
        }
    }

    private Set<Integer> filterLiveDocIds(Set<Integer> docIds) {
        Set<Integer> liveDocIds = new HashSet<>(docIds.size());
        for (Integer docId : docIds) {
            if (docTable.findById(docId).isPresent()) {
                liveDocIds.add(docId);
            }
        }
        return liveDocIds;
    }

    private Map<String, Integer> buildGlobalDocFrequency(List<DiskSegment> segments, Set<String> terms) throws IOException {
        Map<String, Integer> frequencies = new HashMap<>();
        for (String term : terms) {
            Set<Integer> seenDocIds = new HashSet<>();
            for (DiskSegment segment : segments) {
                PostingList postingList = segment.getPostings(term);
                if (postingList == null) {
                    continue;
                }
                for (int docId : postingList.docIds()) {
                    if (docTable.findById(docId).isPresent()) {
                        seenDocIds.add(docId);
                    }
                }
            }
            frequencies.put(term, seenDocIds.size());
        }
        return frequencies;
    }

    private String readContentQuietly(java.nio.file.Path path) {
        try {
            return Files.readString(path);
        } catch (IOException exception) {
            logger.warn("无法读取文档内容: {} - {}", path, exception.getMessage());
            return "";
        }
    }
}
