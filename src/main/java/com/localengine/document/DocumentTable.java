package com.localengine.document;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Optional;

public final class DocumentTable implements AutoCloseable {
    private static final String CREATE_TABLE_SQL = """
            CREATE TABLE IF NOT EXISTS documents (
                doc_id      INTEGER PRIMARY KEY,
                path        TEXT UNIQUE NOT NULL,
                extension   TEXT,
                size_bytes  INTEGER,
                mtime       TEXT,
                doc_type    TEXT,
                token_count INTEGER DEFAULT 0
            )
            """;

    private static final String CREATE_IDX_PATH_SQL = "CREATE INDEX IF NOT EXISTS idx_path ON documents(path)";
    private static final String CREATE_IDX_EXT_SQL = "CREATE INDEX IF NOT EXISTS idx_ext ON documents(extension)";
    private static final String CREATE_IDX_MTIME_SQL = "CREATE INDEX IF NOT EXISTS idx_mtime ON documents(mtime)";
    private static final String ENABLE_WAL_SQL = "PRAGMA journal_mode=WAL";

    private final Connection connection;

    /**
     * 初始化文档元数据表并启用 WAL。
     */
    public DocumentTable(Path dbPath) {
        try {
            this.connection = DriverManager.getConnection("jdbc:sqlite:" + dbPath.toAbsolutePath());
            initializeSchema();
        } catch (SQLException sqlException) {
            throw new IllegalStateException("初始化文档表失败: " + dbPath, sqlException);
        }
    }

    /**
     * 插入文档元数据。
     */
    public void insert(Document document) {
        String sql = """
                INSERT INTO documents(doc_id, path, extension, size_bytes, mtime, doc_type, token_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """;
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            preparedStatement.setInt(1, document.docId());
            preparedStatement.setString(2, normalizePath(document.path().toString()));
            preparedStatement.setString(3, document.extension());
            preparedStatement.setLong(4, document.sizeBytes());
            preparedStatement.setString(5, document.mtime().toString());
            preparedStatement.setString(6, document.docType().name());
            preparedStatement.setInt(7, document.tokenCount());
            preparedStatement.executeUpdate();
        } catch (SQLException sqlException) {
            throw new IllegalStateException("插入文档失败, docId=" + document.docId(), sqlException);
        }
    }

    /**
     * 按文档 ID 更新大小、修改时间与 token 数。
     */
    public void update(int docId, long sizeBytes, Instant mtime, int tokenCount) {
        String sql = """
                UPDATE documents
                SET size_bytes = ?, mtime = ?, token_count = ?
                WHERE doc_id = ?
                """;
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            preparedStatement.setLong(1, sizeBytes);
            preparedStatement.setString(2, mtime.toString());
            preparedStatement.setInt(3, tokenCount);
            preparedStatement.setInt(4, docId);
            preparedStatement.executeUpdate();
        } catch (SQLException sqlException) {
            throw new IllegalStateException("更新文档失败, docId=" + docId, sqlException);
        }
    }

    /**
     * 按路径查找文档。
     */
    public Optional<Document> findByPath(String path) {
        String sql = "SELECT doc_id, path, extension, size_bytes, mtime, doc_type, token_count FROM documents WHERE path = ?";
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            preparedStatement.setString(1, normalizePath(path));
            try (ResultSet resultSet = preparedStatement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return Optional.of(readDocument(resultSet));
            }
        } catch (SQLException sqlException) {
            throw new IllegalStateException("按路径查询失败, path=" + path, sqlException);
        }
    }

    /**
     * 按 ID 查找文档。
     */
    public Optional<Document> findById(int docId) {
        String sql = "SELECT doc_id, path, extension, size_bytes, mtime, doc_type, token_count FROM documents WHERE doc_id = ?";
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            preparedStatement.setInt(1, docId);
            try (ResultSet resultSet = preparedStatement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return Optional.of(readDocument(resultSet));
            }
        } catch (SQLException sqlException) {
            throw new IllegalStateException("按 ID 查询失败, docId=" + docId, sqlException);
        }
    }

    /**
     * 按扩展名过滤文档 ID。
     */
    public List<Integer> findDocIdsByExtension(String extension) {
        String sql = "SELECT doc_id FROM documents WHERE extension = ? ORDER BY doc_id";
        return queryDocIds(sql, statement -> statement.setString(1, extension));
    }

    /**
     * 按文档类型过滤文档 ID。
     */
    public List<Integer> findDocIdsByType(DocType docType) {
        String sql = "SELECT doc_id FROM documents WHERE doc_type = ? ORDER BY doc_id";
        return queryDocIds(sql, statement -> statement.setString(1, docType.name()));
    }

    /**
     * 按修改时间范围过滤文档 ID（闭区间）。
     */
    public List<Integer> findDocIdsByMtimeRange(Instant from, Instant to) {
        String sql = "SELECT doc_id FROM documents WHERE mtime >= ? AND mtime <= ? ORDER BY doc_id";
        return queryDocIds(sql, statement -> {
            statement.setString(1, from.toString());
            statement.setString(2, to.toString());
        });
    }

    /**
     * 按文件大小范围过滤文档 ID（闭区间）。
     */
    public List<Integer> findDocIdsBySizeRange(long min, long max) {
        String sql = "SELECT doc_id FROM documents WHERE size_bytes >= ? AND size_bytes <= ? ORDER BY doc_id";
        return queryDocIds(sql, statement -> {
            statement.setLong(1, min);
            statement.setLong(2, max);
        });
    }

    /**
     * 按路径前缀过滤文档 ID。
     */
    public List<Integer> findDocIdsByPathPrefix(String prefix) {
        String sql = "SELECT doc_id FROM documents WHERE path LIKE ? ORDER BY doc_id";
        return queryDocIds(sql, statement -> statement.setString(1, normalizePath(prefix) + "%"));
    }

    public List<Integer> findDocIdsByFileName(String fileName) {
        String normalizedFileName = normalizePath(fileName).toLowerCase(Locale.ROOT);
        String sql = "SELECT doc_id FROM documents WHERE lower(path) = ? OR lower(path) LIKE ? ESCAPE '#' ORDER BY doc_id";
        return queryDocIds(sql, statement -> {
            statement.setString(1, normalizedFileName);
            statement.setString(2, "%/" + escapeLikeLiteral(normalizedFileName));
        });
    }

    /**
     * 按路径删除文档并返回被删除的 docId。
     */
    public Optional<Integer> deleteByPath(String path) {
        String selectSql = "SELECT doc_id FROM documents WHERE path = ?";
        String deleteSql = "DELETE FROM documents WHERE path = ?";
        try (PreparedStatement selectStatement = connection.prepareStatement(selectSql);
             PreparedStatement deleteStatement = connection.prepareStatement(deleteSql)) {
            connection.setAutoCommit(false);
            String normalizedPath = normalizePath(path);
            selectStatement.setString(1, normalizedPath);
            try (ResultSet resultSet = selectStatement.executeQuery()) {
                if (!resultSet.next()) {
                    connection.rollback();
                    connection.setAutoCommit(true);
                    return Optional.empty();
                }
                int docId = resultSet.getInt(1);
                deleteStatement.setString(1, normalizedPath);
                deleteStatement.executeUpdate();
                connection.commit();
                connection.setAutoCommit(true);
                return Optional.of(docId);
            }
        } catch (SQLException sqlException) {
            rollbackQuietly();
            restoreAutoCommitQuietly();
            throw new IllegalStateException("按路径删除失败, path=" + path, sqlException);
        }
    }

    /**
     * 获取文档总数。
     */
    public int getTotalDocCount() {
        String sql = "SELECT COUNT(*) FROM documents";
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql);
             ResultSet resultSet = preparedStatement.executeQuery()) {
            return resultSet.getInt(1);
        } catch (SQLException sqlException) {
            throw new IllegalStateException("查询文档总数失败", sqlException);
        }
    }

    public void clear() {
        try (Statement statement = connection.createStatement()) {
            statement.executeUpdate("DELETE FROM documents");
        } catch (SQLException sqlException) {
            throw new IllegalStateException("清空文档表失败", sqlException);
        }
    }

    /**
     * 获取平均文档长度（token_count）。
     */
    public double getAverageDocLength() {
        String sql = "SELECT AVG(token_count) FROM documents";
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql);
             ResultSet resultSet = preparedStatement.executeQuery()) {
            double value = resultSet.getDouble(1);
            return resultSet.wasNull() ? 0.0 : value;
        } catch (SQLException sqlException) {
            throw new IllegalStateException("查询平均文档长度失败", sqlException);
        }
    }

    /**
     * 获取下一个可用文档 ID。
     */
    public int nextDocId() {
        String sql = "SELECT COALESCE(MAX(doc_id), 0) + 1 FROM documents";
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql);
             ResultSet resultSet = preparedStatement.executeQuery()) {
            return resultSet.getInt(1);
        } catch (SQLException sqlException) {
            throw new IllegalStateException("获取下一个文档 ID 失败", sqlException);
        }
    }

    /**
     * 查询指定时间后发生变更的文档。
     */
    public List<Document> findChangedSince(Instant since) {
        String sql = """
                SELECT doc_id, path, extension, size_bytes, mtime, doc_type, token_count
                FROM documents
                WHERE mtime > ?
                ORDER BY mtime, doc_id
                """;
        List<Document> changedDocuments = new ArrayList<>();
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            preparedStatement.setString(1, since.toString());
            try (ResultSet resultSet = preparedStatement.executeQuery()) {
                while (resultSet.next()) {
                    changedDocuments.add(readDocument(resultSet));
                }
            }
            return changedDocuments;
        } catch (SQLException sqlException) {
            throw new IllegalStateException("查询变更文档失败, since=" + since, sqlException);
        }
    }

    /**
     * 关闭数据库连接。
     */
    @Override
    public void close() {
        try {
            connection.close();
        } catch (SQLException sqlException) {
            throw new IllegalStateException("关闭数据库连接失败", sqlException);
        }
    }

    /**
     * 读取当前连接的 journal_mode。
     */
    String getJournalMode() {
        try (Statement statement = connection.createStatement();
             ResultSet resultSet = statement.executeQuery("PRAGMA journal_mode")) {
            return resultSet.next() ? resultSet.getString(1) : "";
        } catch (SQLException sqlException) {
            throw new IllegalStateException("读取 journal_mode 失败", sqlException);
        }
    }

    private void initializeSchema() throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute(ENABLE_WAL_SQL);
        }

        connection.setAutoCommit(false);
        try (Statement statement = connection.createStatement()) {
            statement.execute(CREATE_TABLE_SQL);
            statement.execute(CREATE_IDX_PATH_SQL);
            statement.execute(CREATE_IDX_EXT_SQL);
            statement.execute(CREATE_IDX_MTIME_SQL);
            connection.commit();
        } catch (SQLException sqlException) {
            connection.rollback();
            throw sqlException;
        } finally {
            connection.setAutoCommit(true);
        }
    }

    private List<Integer> queryDocIds(String sql, SqlParameterSetter parameterSetter) {
        List<Integer> docIds = new ArrayList<>();
        try (PreparedStatement preparedStatement = connection.prepareStatement(sql)) {
            parameterSetter.set(preparedStatement);
            try (ResultSet resultSet = preparedStatement.executeQuery()) {
                while (resultSet.next()) {
                    docIds.add(resultSet.getInt(1));
                }
            }
            return docIds;
        } catch (SQLException sqlException) {
            throw new IllegalStateException("查询文档 ID 列表失败", sqlException);
        }
    }

    private Document readDocument(ResultSet resultSet) throws SQLException {
        return new Document(
                resultSet.getInt("doc_id"),
                Path.of(resultSet.getString("path")),
                resultSet.getString("extension"),
                resultSet.getLong("size_bytes"),
                Instant.parse(resultSet.getString("mtime")),
                DocType.valueOf(resultSet.getString("doc_type")),
                resultSet.getInt("token_count")
        );
    }

    private String normalizePath(String rawPath) {
        if (rawPath == null) {
            return null;
        }
        return rawPath.replace('\\', '/');
    }

    private String escapeLikeLiteral(String value) {
        return value
            .replace("#", "##")
            .replace("%", "#%")
            .replace("_", "#_");
    }

    private void rollbackQuietly() {
        try {
            connection.rollback();
        } catch (SQLException ignored) {
        }
    }

    private void restoreAutoCommitQuietly() {
        try {
            connection.setAutoCommit(true);
        } catch (SQLException ignored) {
        }
    }

    @FunctionalInterface
    private interface SqlParameterSetter {
        void set(PreparedStatement preparedStatement) throws SQLException;
    }
}
