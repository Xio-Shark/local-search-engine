package com.localengine.cli;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.localengine.config.Constants;
import com.localengine.document.DocumentTable;
import com.localengine.gui.DesktopApp;
import com.localengine.highlight.Snippet;
import com.localengine.index.IndexManager;
import com.localengine.index.IndexStatus;
import com.localengine.query.QueryEngine;
import com.localengine.query.SearchResult;
import picocli.CommandLine;
import picocli.CommandLine.Command;
import picocli.CommandLine.Option;
import picocli.CommandLine.Parameters;
import picocli.CommandLine.ParentCommand;

import java.io.IOException;
import java.nio.file.Path;
import java.util.List;
import java.util.concurrent.Callable;

@Command(
    name = "lse",
    description = "🔍 高性能本地文件全文搜索引擎",
    mixinStandardHelpOptions = true,
    version = "1.0.0",
    subcommands = {
        MainCommand.IndexSubcommand.class,
        MainCommand.SearchSubcommand.class,
        MainCommand.StatusSubcommand.class,
        MainCommand.RebuildSubcommand.class
    }
)
public class MainCommand implements Callable<Integer> {

    @Option(names = {"--gui"}, description = "启动图形界面")
    private boolean guiMode;

    @Option(names = {"--index-dir"}, description = "索引目录路径", defaultValue = "./index")
    private Path indexDir;

    @Option(names = {"--note-dir"}, description = "笔记目录路径（可指定多个）")
    private List<Path> noteDirs;

    @Option(names = {"--threads"}, description = "索引线程数", defaultValue = "4")
    private int threads;

    public static void main(String[] args) {
        int exitCode = new CommandLine(new MainCommand()).execute(args);
        System.exit(exitCode);
    }

    @Override
    public Integer call() {
        if (guiMode) {
            try {
                DesktopApp.launchAndWait();
                return 0;
            } catch (Exception exception) {
                System.err.println("❌ 图形界面启动失败: " + exception.getMessage());
                exception.printStackTrace();
                return 1;
            }
        }
        System.out.println("🔍 高性能本地文件全文搜索引擎");
        System.out.println("使用 --help 查看帮助信息");
        return 0;
    }

    private int resolveThreadCount() {
        if (threads <= 0) {
            System.err.printf("⚠️ 非法线程数 %d，已回退为默认值 %d%n", threads, Constants.DEFAULT_INDEX_THREADS);
            return Constants.DEFAULT_INDEX_THREADS;
        }
        if (threads > Constants.MAX_INDEX_THREADS) {
            System.err.printf("⚠️ 线程数 %d 超过安全上限 %d，已自动限制%n", threads, Constants.MAX_INDEX_THREADS);
            return Constants.MAX_INDEX_THREADS;
        }
        return threads;
    }

    private int sanitizeSearchLimit(int rawLimit) {
        if (rawLimit < 0) {
            System.err.printf("⚠️ limit=%d 非法，已使用 0%n", rawLimit);
            return 0;
        }
        if (rawLimit > Constants.MAX_SEARCH_LIMIT) {
            System.err.printf("⚠️ limit=%d 超过上限 %d，已自动限制%n", rawLimit, Constants.MAX_SEARCH_LIMIT);
            return Constants.MAX_SEARCH_LIMIT;
        }
        return rawLimit;
    }

    private String sanitizeQuery(String rawQuery) {
        if (rawQuery == null) {
            return "";
        }
        String trimmed = rawQuery.trim();
        if (trimmed.length() > Constants.MAX_QUERY_LENGTH) {
            throw new CommandLine.ParameterException(new CommandLine(this),
                "查询长度超过限制（最大 " + Constants.MAX_QUERY_LENGTH + " 字符）");
        }
        return trimmed;
    }

    @Command(name = "index", description = "📂 构建或增量更新索引")
    static class IndexSubcommand implements Callable<Integer> {

        @Parameters(description = "要索引的源目录或文件路径", arity = "1..*")
        private List<Path> sourcePaths;

        @ParentCommand
        private MainCommand main;

        @Override
        public Integer call() {
            System.out.println("🚀 开始索引...");
            System.out.println("📁 索引目录: " + main.indexDir);
            System.out.println("📂 源路径: " + sourcePaths);
            int effectiveThreads = main.resolveThreadCount();
            System.out.println("🔧 线程数: " + effectiveThreads);

            try (IndexManager indexManager = new IndexManager(main.indexDir, effectiveThreads)) {
                long start = System.currentTimeMillis();
                indexManager.buildIndex(sourcePaths);
                long elapsed = System.currentTimeMillis() - start;
                IndexStatus status = indexManager.getStatus();

                System.out.println("✅ 索引完成！");
                System.out.println("📊 统计:");
                System.out.println("   文档数: " + status.docCount());
                System.out.println("   词条数: " + status.termCount());
                System.out.println("   用时: " + elapsed + "ms");
                return 0;
            } catch (Exception exception) {
                System.err.println("❌ 索引失败: " + exception.getMessage());
                exception.printStackTrace();
                return 1;
            }
        }
    }

    @Command(name = "search", description = "🔎 执行搜索查询")
    static class SearchSubcommand implements Callable<Integer> {

        @Parameters(description = "搜索查询语句", arity = "1")
        private String query;

        @Option(names = {"-l", "--limit"}, description = "返回结果数量限制", defaultValue = "10")
        private int limit;

        @Option(names = {"-f", "--format"}, description = "输出格式 (text|json)", defaultValue = "text")
        private String format;

        @ParentCommand
        private MainCommand main;

        @Override
        public Integer call() {
            try (IndexManager indexManager = new IndexManager(main.indexDir, main.resolveThreadCount());
                 DocumentTable docTable = new DocumentTable(main.indexDir.resolve("documents.db"))) {
                QueryEngine queryEngine = new QueryEngine(indexManager, docTable);
                String safeQuery = main.sanitizeQuery(query);
                int safeLimit = main.sanitizeSearchLimit(limit);
                SearchResult result = queryEngine.search(safeQuery, safeLimit);

                System.out.println("🔍 查询: \"" + safeQuery + "\"");
                System.out.println();

                if ("json".equalsIgnoreCase(format)) {
                    printJsonResult(result);
                } else {
                    printTextResult(result);
                }

                System.out.println();
                System.out.println("📊 共 " + result.totalMatches() + " 条匹配，用时 " + result.elapsedMs() + "ms");
                return 0;
            } catch (Exception exception) {
                System.err.println("❌ 搜索失败: " + exception.getMessage());
                exception.printStackTrace();
                return 1;
            }
        }

        private void printTextResult(SearchResult result) {
            if (result.hits().isEmpty()) {
                System.out.println("⚠️ 未找到匹配结果");
                return;
            }

            int rank = 1;
            for (var hit : result.hits()) {
                System.out.println("─────────────────────────────────");
                System.out.printf("%d. %s (score: %.4f)%n", rank++, hit.document().path(), hit.score());
                for (Snippet snippet : hit.snippets()) {
                    System.out.println("   " + snippet.text().replace("\n", " "));
                }
                System.out.println();
            }
        }

        private void printJsonResult(SearchResult result) throws IOException {
            ObjectMapper mapper = new ObjectMapper();
            mapper.registerModule(new JavaTimeModule());
            System.out.println(mapper.writerWithDefaultPrettyPrinter().writeValueAsString(result));
        }
    }

    @Command(name = "status", description = "📊 查看索引统计信息")
    static class StatusSubcommand implements Callable<Integer> {

        @ParentCommand
        private MainCommand main;

        @Override
        public Integer call() {
            try (IndexManager indexManager = new IndexManager(main.indexDir, main.resolveThreadCount())) {
                IndexStatus status = indexManager.getStatus();

                System.out.println("📊 索引状态");
                System.out.println("═══════════");
                System.out.println("📁 索引目录: " + main.indexDir);
                System.out.println("📄 文档总数: " + status.docCount());
                System.out.println("🔤 词条总数: " + status.termCount());
                System.out.println("📦 段数量: " + status.segmentCount());
                System.out.println("💾 索引大小: " + formatBytes(status.indexSizeBytes()));
                return 0;
            } catch (Exception exception) {
                System.err.println("❌ 获取状态失败: " + exception.getMessage());
                return 1;
            }
        }

        private String formatBytes(long bytes) {
            if (bytes < 1024) {
                return bytes + " B";
            }
            if (bytes < 1024 * 1024L) {
                return String.format("%.2f KB", bytes / 1024.0);
            }
            if (bytes < 1024 * 1024L * 1024L) {
                return String.format("%.2f MB", bytes / (1024.0 * 1024.0));
            }
            return String.format("%.2f GB", bytes / (1024.0 * 1024.0 * 1024.0));
        }
    }

    @Command(name = "rebuild", description = "🔄 全量重建索引（删除现有索引）")
    static class RebuildSubcommand implements Callable<Integer> {

        @Parameters(description = "要索引的源目录或文件路径", arity = "1..*")
        private List<Path> sourcePaths;

        @Option(names = {"--yes"}, description = "确认删除", defaultValue = "false")
        private boolean confirmed;

        @ParentCommand
        private MainCommand main;

        @Override
        public Integer call() {
            if (!confirmed) {
                System.out.println("⚠️ 警告: 这将删除现有索引并重新构建");
                System.out.println("使用 --yes 确认");
                return 1;
            }

            final int effectiveThreads = main.resolveThreadCount();
            System.out.println("🔄 开始重建索引...");
            System.out.println("🔧 线程数: " + effectiveThreads);
            try (IndexManager indexManager = new IndexManager(main.indexDir, effectiveThreads)) {
                long start = System.currentTimeMillis();
                indexManager.rebuild(sourcePaths);
                long elapsed = System.currentTimeMillis() - start;
                System.out.println("✅ 重建完成！用时 " + elapsed + "ms");
                return 0;
            } catch (Exception exception) {
                System.err.println("❌ 重建失败: " + exception.getMessage());
                exception.printStackTrace();
                return 1;
            }
        }
    }

}
