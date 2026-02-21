package com.localengine;

import com.localengine.index.IndexManager;
import com.localengine.query.QueryEngine;
import com.localengine.document.DocumentTable;
import com.localengine.text.CompositeTokenizer;
import org.openjdk.jmh.annotations.*;
import org.openjdk.jmh.runner.Runner;
import org.openjdk.jmh.runner.options.Options;
import org.openjdk.jmh.runner.options.OptionsBuilder;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.concurrent.TimeUnit;

/**
 * 索引性能基准测试
 */
@BenchmarkMode(Mode.Throughput)
@OutputTimeUnit(TimeUnit.SECONDS)
@State(Scope.Benchmark)
@Fork(value = 1, jvmArgs = {"-Xms2g", "-Xmx2g"})
@Warmup(iterations = 3)
@Measurement(iterations = 5)
public class IndexBenchmark {

    @State(Scope.Thread)
    public static class IndexState {
        Path tempDir;
        Path indexDir;
        Path sourceDir;
        IndexManager indexManager;

        @Setup
        public void setup() throws IOException {
            tempDir = Files.createTempDirectory("benchmark");
            indexDir = tempDir.resolve("index");
            sourceDir = tempDir.resolve("source");
            Files.createDirectories(sourceDir);
            
            // 创建1000个测试文件
            for (int i = 0; i < 1000; i++) {
                String content = generateDocument(i);
                Files.writeString(sourceDir.resolve("doc" + i + ".md"), content);
            }
            
            indexManager = new IndexManager(indexDir, 4);
        }

        @TearDown
        public void tearDown() throws IOException {
            if (indexManager != null) {
                indexManager.close();
            }
            deleteDirectory(tempDir);
        }

        private String generateDocument(int index) {
            return "Document " + index + " content. " +
                   "This is a test document for benchmarking. " +
                   "It contains various words like Java, Python, programming, " +
                   "search, index, document, file, content, data, " +
                   "performance, benchmark, test, example. " +
                   "The quick brown fox jumps over the lazy dog. " +
                   " repeated text to increase size.".repeat(5);
        }

        private void deleteDirectory(Path dir) throws IOException {
            if (!Files.exists(dir)) return;
            Files.walk(dir)
                .sorted((a, b) -> -a.compareTo(b))
                .forEach(p -> {
                    try {
                        Files.deleteIfExists(p);
                    } catch (IOException e) {
                        // ignore
                    }
                });
        }
    }

    @Benchmark
    public void indexThroughput(IndexState state) throws IOException {
        state.indexManager.buildIndex(java.util.List.of(state.sourceDir));
    }

    @BenchmarkMode(Mode.AverageTime)
    @OutputTimeUnit(TimeUnit.MILLISECONDS)
    @State(Scope.Benchmark)
    public static class QueryLatencyState {
        Path tempDir;
        Path indexDir;
        Path sourceDir;
        IndexManager indexManager;
        DocumentTable docTable;
        QueryEngine queryEngine;

        @Setup
        public void setup() throws IOException {
            tempDir = Files.createTempDirectory("benchmark");
            indexDir = tempDir.resolve("index");
            sourceDir = tempDir.resolve("source");
            Files.createDirectories(sourceDir);
            
            // 创建10000个测试文件
            for (int i = 0; i < 10000; i++) {
                String content = "Document " + i + " about " + 
                    (i % 10 == 0 ? "Java programming" : 
                     i % 10 == 1 ? "Python data science" :
                     i % 10 == 2 ? "machine learning" :
                     "general content") + 
                    " with various keywords for search testing.";
                Files.writeString(sourceDir.resolve("doc" + i + ".md"), content);
            }
            
            indexManager = new IndexManager(indexDir, 4);
            indexManager.buildIndex(java.util.List.of(sourceDir));
            
        docTable = new DocumentTable(indexDir.resolve("documents.db"));
            queryEngine = new QueryEngine(indexManager, docTable);
        }

        @TearDown
        public void tearDown() throws IOException {
            if (docTable != null) {
                docTable.close();
            }
            if (indexManager != null) {
                indexManager.close();
            }
            deleteDirectory(tempDir);
        }

        private void deleteDirectory(Path dir) throws IOException {
            if (!Files.exists(dir)) return;
            Files.walk(dir)
                .sorted((a, b) -> -a.compareTo(b))
                .forEach(p -> {
                    try {
                        Files.deleteIfExists(p);
                    } catch (IOException e) {
                        // ignore
                    }
                });
        }
    }

    @Benchmark
    @BenchmarkMode(Mode.AverageTime)
    @OutputTimeUnit(TimeUnit.MILLISECONDS)
    public double queryLatencySimple(QueryLatencyState state) throws IOException {
        return state.queryEngine.search("Java", 10).elapsedMs();
    }

    @Benchmark
    @BenchmarkMode(Mode.AverageTime)
    @OutputTimeUnit(TimeUnit.MILLISECONDS)
    public double queryLatencyPhrase(QueryLatencyState state) throws IOException {
        return state.queryEngine.search("\"machine learning\"", 10).elapsedMs();
    }

    @Benchmark
    @BenchmarkMode(Mode.AverageTime)
    @OutputTimeUnit(TimeUnit.MILLISECONDS)
    public double queryLatencyBoolean(QueryLatencyState state) throws IOException {
        return state.queryEngine.search("Java AND programming", 10).elapsedMs();
    }

    public static void main(String[] args) throws Exception {
        Options opt = new OptionsBuilder()
            .include(IndexBenchmark.class.getSimpleName())
            .forks(1)
            .build();
        new Runner(opt).run();
    }
}
