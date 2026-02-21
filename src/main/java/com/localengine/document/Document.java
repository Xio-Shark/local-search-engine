package com.localengine.document;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

public record Document(
        int docId,
        Path path,
        String extension,
        long sizeBytes,
        Instant mtime,
        DocType docType,
        int tokenCount
) {
    private static final Set<String> CODE_EXTENSIONS = Set.of(
            "java", "kt", "py", "js", "ts", "cpp", "c", "h", "hpp", "rs", "go", "rb", "php", "swift",
            "cs", "scala", "groovy", "sql", "sh", "bash", "zsh", "ps1", "vim", "lua", "perl", "r",
            "matlab", "dart", "kotlin"
    );

    private static final Set<String> CONFIG_EXTENSIONS = Set.of(
            "json", "xml", "yaml", "yml", "toml", "ini", "conf", "cfg", "properties", "env", "gradle",
            "maven", "cmake", "dockerfile", "gitignore"
    );

    private static final Set<String> DOC_EXTENSIONS = Set.of(
            "md", "txt", "rst", "adoc", "org", "wiki", "doc", "docx", "pdf", "html", "htm"
    );

    private static final Set<String> DATA_EXTENSIONS = Set.of(
            "csv", "tsv", "xlsx", "xls", "db", "sqlite", "parquet"
    );

    public static Document ofFile(int docId, Path path, List<Path> notePaths) {
        Path normalizedPath = path.toAbsolutePath().normalize();
        String normalizedExtension = extractExtension(normalizedPath);
        Instant modifiedTime;
        long fileSize;
        try {
            modifiedTime = Files.getLastModifiedTime(normalizedPath).toInstant();
            fileSize = Files.size(normalizedPath);
        } catch (IOException ioException) {
            throw new IllegalStateException("读取文件元数据失败: " + normalizedPath, ioException);
        }

        DocType inferredType = inferDocType(normalizedPath, normalizedExtension, notePaths);
        return new Document(docId, normalizedPath, normalizedExtension, fileSize, modifiedTime, inferredType, 0);
    }

    public Document withTokenCount(int tokenCount) {
        return new Document(docId, path, extension, sizeBytes, mtime, docType, tokenCount);
    }

    private static DocType inferDocType(Path path, String extension, List<Path> notePaths) {
        if (isNotePath(path, notePaths)) {
            return DocType.NOTE;
        }
        if (CODE_EXTENSIONS.contains(extension)) {
            return DocType.CODE;
        }
        if (CONFIG_EXTENSIONS.contains(extension)) {
            return DocType.CONFIG;
        }
        if (DOC_EXTENSIONS.contains(extension)) {
            return DocType.DOC;
        }
        if (DATA_EXTENSIONS.contains(extension)) {
            return DocType.DATA;
        }
        return DocType.OTHER;
    }

    private static boolean isNotePath(Path path, List<Path> notePaths) {
        if (notePaths == null || notePaths.isEmpty()) {
            return false;
        }
        Set<Path> normalizedNotePaths = new HashSet<>();
        for (Path notePath : notePaths) {
            if (notePath != null) {
                normalizedNotePaths.add(notePath.toAbsolutePath().normalize());
            }
        }
        return normalizedNotePaths.contains(path);
    }

    private static String extractExtension(Path path) {
        String fileName = path.getFileName() == null ? "" : path.getFileName().toString();
        int lastDotIndex = fileName.lastIndexOf('.');
        if (lastDotIndex >= 0 && lastDotIndex < fileName.length() - 1) {
            return fileName.substring(lastDotIndex + 1).toLowerCase(Locale.ROOT);
        }
        return fileName.toLowerCase(Locale.ROOT);
    }
}
