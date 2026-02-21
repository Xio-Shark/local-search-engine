package com.localengine.gui;

import com.localengine.document.DocumentTable;
import com.localengine.highlight.HighlightSpan;
import com.localengine.highlight.Snippet;
import com.localengine.index.IndexManager;
import com.localengine.index.IndexStatus;
import com.localengine.query.QueryEngine;
import com.localengine.query.SearchHit;
import com.localengine.query.SearchResult;

import javax.swing.BorderFactory;
import javax.swing.BoxLayout;
import javax.swing.JButton;
import javax.swing.JCheckBox;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JOptionPane;
import javax.swing.JPanel;
import javax.swing.JScrollPane;
import javax.swing.JSpinner;
import javax.swing.JTabbedPane;
import javax.swing.JTextArea;
import javax.swing.JTextField;
import javax.swing.JTextPane;
import javax.swing.SpinnerNumberModel;
import javax.swing.SwingUtilities;
import javax.swing.SwingWorker;
import javax.swing.WindowConstants;
import javax.swing.text.BadLocationException;
import javax.swing.text.SimpleAttributeSet;
import javax.swing.text.StyleConstants;
import javax.swing.text.StyledDocument;
import java.awt.BorderLayout;
import java.awt.FlowLayout;
import java.awt.Font;
import java.awt.GraphicsEnvironment;
import java.awt.GridLayout;
import java.awt.event.WindowAdapter;
import java.awt.event.WindowEvent;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.CountDownLatch;
import java.util.function.Consumer;

public final class DesktopApp {
    private DesktopApp() {
    }

    static String toFileNameQuery(String fileName) {
        String escapedFileName = fileName.replace("\\", "\\\\").replace("\"", "\\\"");
        return "filename:\"" + escapedFileName + "\"";
    }

    static List<Path> parseSourcePaths(String sourceText) {
        String[] rawLines = sourceText.split("\\R");
        List<Path> paths = new ArrayList<>();
        for (String rawLine : rawLines) {
            String trimmedLine = rawLine.trim();
            if (trimmedLine.isEmpty()) {
                continue;
            }
            try {
                paths.add(Path.of(trimmedLine));
            } catch (InvalidPathException invalidPathException) {
                throw new IllegalArgumentException("源路径非法: " + trimmedLine);
            }
        }
        if (paths.isEmpty()) {
            throw new IllegalArgumentException("请至少提供一个源路径");
        }
        return paths;
    }

    static Path parseIndexDir(String rawPath) {
        String trimmedPath = rawPath.trim();
        if (trimmedPath.isEmpty()) {
            throw new IllegalArgumentException("索引目录不能为空");
        }
        try {
            return Path.of(trimmedPath);
        } catch (InvalidPathException invalidPathException) {
            throw new IllegalArgumentException("索引目录非法: " + trimmedPath);
        }
    }

    static String stripAnsi(String text) {
        return text == null ? "" : text.replaceAll(MainFrame.ANSI_ESCAPE_REGEX, "");
    }

    static String formatBytes(long bytes) {
        if (bytes < 1024) {
            return bytes + " B";
        }
        if (bytes < 1024L * 1024L) {
            return String.format("%.2f KB", bytes / 1024.0);
        }
        if (bytes < 1024L * 1024L * 1024L) {
            return String.format("%.2f MB", bytes / (1024.0 * 1024.0));
        }
        return String.format("%.2f GB", bytes / (1024.0 * 1024.0 * 1024.0));
    }

    static void renderSearchResult(JTextPane searchResultPane, SearchResult result) {
        StyledDocument document = searchResultPane.getStyledDocument();
        try {
            document.remove(0, document.getLength());
            if (result.hits().isEmpty()) {
                appendText(document, "未找到匹配结果\n", createNormalStyle());
                return;
            }

            int rank = 1;
            for (SearchHit hit : result.hits()) {
                appendText(document,
                    rank++ + ". " + hit.document().path() + "  (score=" + String.format("%.4f", hit.score()) + ")\n",
                    createHeaderStyle());

                for (Snippet snippet : hit.snippets()) {
                    appendText(document, "   ", createNormalStyle());
                    String rawSnippet = stripAnsi(snippet.text()).replace('\n', ' ');
                    appendSnippetWithHighlights(document, rawSnippet, snippet.highlights());
                    appendText(document, "\n", createNormalStyle());
                }
                appendText(document, "\n", createNormalStyle());
            }

            appendText(document,
                "总命中: " + result.totalMatches() + "，耗时: " + result.elapsedMs() + "ms\n",
                createHeaderStyle());
            searchResultPane.setCaretPosition(0);
        } catch (BadLocationException badLocationException) {
            throw new IllegalStateException("渲染搜索结果失败", badLocationException);
        }
    }

    static void appendSnippetWithHighlights(StyledDocument document, String snippetText, List<HighlightSpan> highlights)
        throws BadLocationException {
        if (snippetText == null || snippetText.isEmpty()) {
            return;
        }
        if (highlights == null || highlights.isEmpty()) {
            appendText(document, snippetText, createNormalStyle());
            return;
        }

        int cursor = 0;
        for (HighlightSpan highlight : highlights) {
            int start = Math.max(0, Math.min(highlight.start(), snippetText.length()));
            int end = Math.max(start, Math.min(highlight.end(), snippetText.length()));
            if (start > cursor) {
                appendText(document, snippetText.substring(cursor, start), createNormalStyle());
            }
            if (end > start) {
                appendText(document, snippetText.substring(start, end), createHighlightStyle());
            }
            cursor = end;
        }
        if (cursor < snippetText.length()) {
            appendText(document, snippetText.substring(cursor), createNormalStyle());
        }
    }

    static void appendText(StyledDocument document, String text, SimpleAttributeSet style) throws BadLocationException {
        document.insertString(document.getLength(), text, style);
    }

    static SimpleAttributeSet createNormalStyle() {
        SimpleAttributeSet style = new SimpleAttributeSet();
        StyleConstants.setFontFamily(style, Font.MONOSPACED);
        StyleConstants.setFontSize(style, 12);
        return style;
    }

    static SimpleAttributeSet createHeaderStyle() {
        SimpleAttributeSet style = createNormalStyle();
        StyleConstants.setBold(style, true);
        return style;
    }

    static SimpleAttributeSet createHighlightStyle() {
        SimpleAttributeSet style = createNormalStyle();
        StyleConstants.setBold(style, true);
        StyleConstants.setBackground(style, new java.awt.Color(255, 241, 118));
        return style;
    }

    public static void launchAndWait() throws Exception {
        if (GraphicsEnvironment.isHeadless()) {
            throw new IllegalStateException("当前环境不支持图形界面");
        }

        CountDownLatch closeSignal = new CountDownLatch(1);
        Holder<RuntimeException> startupFailure = new Holder<>();

        SwingUtilities.invokeAndWait(() -> {
            try {
                MainFrame frame = new MainFrame();
                frame.addWindowListener(new WindowAdapter() {
                    @Override
                    public void windowClosed(WindowEvent windowEvent) {
                        closeSignal.countDown();
                    }
                });
                frame.setVisible(true);
            } catch (RuntimeException runtimeException) {
                startupFailure.value = runtimeException;
                closeSignal.countDown();
            }
        });

        if (startupFailure.value != null) {
            throw startupFailure.value;
        }
        closeSignal.await();
    }

    private static final class MainFrame extends JFrame {
        private static final DateTimeFormatter LOG_TIME_FORMAT = DateTimeFormatter.ofPattern("HH:mm:ss");
        private static final String ANSI_ESCAPE_REGEX = "\\u001B\\[[;\\d]*m";

        private final JTextField indexDirField = new JTextField("./index", 30);
        private final JSpinner threadSpinner = new JSpinner(new SpinnerNumberModel(4, 1, 64, 1));
        private final JTextArea sourcePathsArea = new JTextArea(6, 60);
        private final JCheckBox rebuildConfirmBox = new JCheckBox("我确认执行全量重建（会删除现有索引）");

        private final JTextField queryField = new JTextField(42);
        private final JTextField quickFileNameField = new JTextField(18);
        private final JSpinner limitSpinner = new JSpinner(new SpinnerNumberModel(10, 1, 200, 1));
        private final JTextPane searchResultPane = new JTextPane();

        private final JLabel docCountLabel = new JLabel("0");
        private final JLabel termCountLabel = new JLabel("0");
        private final JLabel segmentCountLabel = new JLabel("0");
        private final JLabel indexSizeLabel = new JLabel("0 B");

        private final JTextArea logArea = new JTextArea(8, 80);
        private final List<JButton> actionButtons = new ArrayList<>();

        private MainFrame() {
            setTitle("本地搜索引擎 - 图形界面");
            setDefaultCloseOperation(WindowConstants.DISPOSE_ON_CLOSE);
            setSize(980, 760);
            setLocationRelativeTo(null);

            JPanel rootPanel = new JPanel(new BorderLayout(8, 8));
            rootPanel.setBorder(BorderFactory.createEmptyBorder(10, 10, 10, 10));
            rootPanel.add(createCommonConfigPanel(), BorderLayout.NORTH);

            JTabbedPane tabbedPane = new JTabbedPane();
            tabbedPane.addTab("索引", createIndexPanel());
            tabbedPane.addTab("搜索", createSearchPanel());
            tabbedPane.addTab("状态", createStatusPanel());
            rootPanel.add(tabbedPane, BorderLayout.CENTER);

            rootPanel.add(createLogPanel(), BorderLayout.SOUTH);
            setContentPane(rootPanel);
        }

        private JPanel createCommonConfigPanel() {
            JPanel configPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
            configPanel.setBorder(BorderFactory.createTitledBorder("全局配置"));
            configPanel.add(new JLabel("索引目录:"));
            configPanel.add(indexDirField);
            configPanel.add(new JLabel("线程数:"));
            configPanel.add(threadSpinner);
            return configPanel;
        }

        private JPanel createIndexPanel() {
            JPanel panel = new JPanel(new BorderLayout(8, 8));

            sourcePathsArea.setLineWrap(true);
            sourcePathsArea.setWrapStyleWord(true);
            sourcePathsArea.setText("docs");
            JScrollPane sourceScrollPane = new JScrollPane(sourcePathsArea);
            sourceScrollPane.setBorder(BorderFactory.createTitledBorder("源路径（每行一个目录或文件）"));
            panel.add(sourceScrollPane, BorderLayout.CENTER);

            JPanel actionPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
            JButton indexButton = new JButton("构建/增量索引");
            registerActionButton(indexButton);
            indexButton.addActionListener(event -> runIndexTask());

            JButton rebuildButton = new JButton("全量重建");
            registerActionButton(rebuildButton);
            rebuildButton.addActionListener(event -> runRebuildTask());

            actionPanel.add(indexButton);
            actionPanel.add(rebuildButton);
            actionPanel.add(rebuildConfirmBox);
            panel.add(actionPanel, BorderLayout.SOUTH);

            return panel;
        }

        private JPanel createSearchPanel() {
            JPanel panel = new JPanel(new BorderLayout(8, 8));

            JPanel formPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
            formPanel.add(new JLabel("查询语句:"));
            formPanel.add(queryField);
            formPanel.add(new JLabel("限制:"));
            formPanel.add(limitSpinner);
            JButton searchButton = new JButton("执行搜索");
            registerActionButton(searchButton);
            searchButton.addActionListener(event -> runSearchTask());
            formPanel.add(searchButton);

            formPanel.add(new JLabel("文件名快速检索:"));
            formPanel.add(quickFileNameField);
            JButton quickFileNameButton = new JButton("按文件名搜索");
            registerActionButton(quickFileNameButton);
            quickFileNameButton.addActionListener(event -> runQuickFileNameSearchTask());
            formPanel.add(quickFileNameButton);
            panel.add(formPanel, BorderLayout.NORTH);

            searchResultPane.setEditable(false);
            searchResultPane.setFont(new Font(Font.MONOSPACED, Font.PLAIN, 12));
            panel.add(new JScrollPane(searchResultPane), BorderLayout.CENTER);
            return panel;
        }

        private JPanel createStatusPanel() {
            JPanel panel = new JPanel(new BorderLayout(8, 8));
            JPanel statsGrid = new JPanel(new GridLayout(4, 2, 8, 8));
            statsGrid.setBorder(BorderFactory.createTitledBorder("索引状态"));
            statsGrid.add(new JLabel("文档总数:"));
            statsGrid.add(docCountLabel);
            statsGrid.add(new JLabel("词条总数:"));
            statsGrid.add(termCountLabel);
            statsGrid.add(new JLabel("段数量:"));
            statsGrid.add(segmentCountLabel);
            statsGrid.add(new JLabel("索引大小:"));
            statsGrid.add(indexSizeLabel);

            JButton refreshButton = new JButton("刷新状态");
            registerActionButton(refreshButton);
            refreshButton.addActionListener(event -> runStatusTask());

            JPanel topPanel = new JPanel(new FlowLayout(FlowLayout.LEFT));
            topPanel.add(refreshButton);

            panel.add(topPanel, BorderLayout.NORTH);
            panel.add(statsGrid, BorderLayout.CENTER);
            return panel;
        }

        private JScrollPane createLogPanel() {
            logArea.setEditable(false);
            logArea.setLineWrap(true);
            logArea.setWrapStyleWord(true);
            JScrollPane logScrollPane = new JScrollPane(logArea);
            logScrollPane.setBorder(BorderFactory.createTitledBorder("运行日志"));
            return logScrollPane;
        }

        private void runIndexTask() {
            List<Path> sourcePaths;
            try {
                sourcePaths = parseSourcePaths();
            } catch (IllegalArgumentException illegalArgumentException) {
                showError(illegalArgumentException.getMessage());
                return;
            }

            executeAsync("构建索引", () -> {
                try (IndexManager indexManager = new IndexManager(resolveIndexDir(), resolveThreads())) {
                    indexManager.buildIndex(sourcePaths);
                    return indexManager.getStatus();
                }
            }, status -> {
                applyStatus(status);
                appendLog("索引完成: 文档=" + status.docCount() + "，词条=" + status.termCount());
            });
        }

        private void runRebuildTask() {
            if (!rebuildConfirmBox.isSelected()) {
                showError("请先勾选重建确认选项");
                return;
            }

            List<Path> sourcePaths;
            try {
                sourcePaths = parseSourcePaths();
            } catch (IllegalArgumentException illegalArgumentException) {
                showError(illegalArgumentException.getMessage());
                return;
            }

            executeAsync("全量重建", () -> {
                try (IndexManager indexManager = new IndexManager(resolveIndexDir(), resolveThreads())) {
                    indexManager.rebuild(sourcePaths);
                    return indexManager.getStatus();
                }
            }, status -> {
                applyStatus(status);
                appendLog("重建完成: 文档=" + status.docCount() + "，词条=" + status.termCount());
            });
        }

        private void runSearchTask() {
            String query = queryField.getText().trim();
            if (query.isEmpty()) {
                showError("查询语句不能为空");
                return;
            }

            runSearchWithQuery(query);
        }

        private void runQuickFileNameSearchTask() {
            String fileName = quickFileNameField.getText().trim();
            if (fileName.isEmpty()) {
                showError("文件名不能为空");
                return;
            }

            String query = toFileNameQuery(fileName);
            queryField.setText(query);
            runSearchWithQuery(query);
        }

        private String toFileNameQuery(String fileName) {
            return DesktopApp.toFileNameQuery(fileName);
        }

        private void runSearchWithQuery(String query) {
            executeAsync("执行搜索", () -> {
                try (IndexManager indexManager = new IndexManager(resolveIndexDir(), resolveThreads());
                     DocumentTable documentTable = new DocumentTable(resolveIndexDir().resolve("documents.db"))) {
                    QueryEngine queryEngine = new QueryEngine(indexManager, documentTable);
                    return queryEngine.search(query, (Integer) limitSpinner.getValue());
                }
            }, result -> {
                renderSearchResult(result);
                appendLog("搜索完成: 命中=" + result.totalMatches() + "，耗时=" + result.elapsedMs() + "ms");
            });
        }

        private void runStatusTask() {
            executeAsync("刷新状态", () -> {
                try (IndexManager indexManager = new IndexManager(resolveIndexDir(), resolveThreads())) {
                    return indexManager.getStatus();
                }
            }, status -> {
                applyStatus(status);
                appendLog("状态已刷新");
            });
        }

        private <T> void executeAsync(String taskName, Callable<T> action, Consumer<T> onSuccess) {
            setActionButtonsEnabled(false);
            appendLog("开始: " + taskName);
            SwingWorker<T, Void> worker = new SwingWorker<>() {
                @Override
                protected T doInBackground() throws Exception {
                    return action.call();
                }

                @Override
                protected void done() {
                    setActionButtonsEnabled(true);
                    try {
                        T result = get();
                        onSuccess.accept(result);
                    } catch (Exception exception) {
                        appendLog("失败: " + taskName + " - " + exception.getMessage());
                        showError(taskName + "失败: " + exception.getMessage());
                    }
                }
            };
            worker.execute();
        }

        private List<Path> parseSourcePaths() {
            return DesktopApp.parseSourcePaths(sourcePathsArea.getText());
        }

        private Path resolveIndexDir() {
            return DesktopApp.parseIndexDir(indexDirField.getText());
        }

        private int resolveThreads() {
            return (Integer) threadSpinner.getValue();
        }

        private void applyStatus(IndexStatus status) {
            docCountLabel.setText(String.valueOf(status.docCount()));
            termCountLabel.setText(String.valueOf(status.termCount()));
            segmentCountLabel.setText(String.valueOf(status.segmentCount()));
            indexSizeLabel.setText(formatBytes(status.indexSizeBytes()));
        }

        private void renderSearchResult(SearchResult result) {
            DesktopApp.renderSearchResult(searchResultPane, result);
        }

        private void appendSnippetWithHighlights(StyledDocument document, String snippetText, List<HighlightSpan> highlights)
            throws BadLocationException {
            DesktopApp.appendSnippetWithHighlights(document, snippetText, highlights);
        }

        private void appendText(StyledDocument document, String text, SimpleAttributeSet style)
            throws BadLocationException {
            DesktopApp.appendText(document, text, style);
        }

        private SimpleAttributeSet createNormalStyle() {
            return DesktopApp.createNormalStyle();
        }

        private SimpleAttributeSet createHeaderStyle() {
            return DesktopApp.createHeaderStyle();
        }

        private SimpleAttributeSet createHighlightStyle() {
            return DesktopApp.createHighlightStyle();
        }

        private String stripAnsi(String text) {
            return DesktopApp.stripAnsi(text);
        }

        private String formatBytes(long bytes) {
            return DesktopApp.formatBytes(bytes);
        }

        private void appendLog(String message) {
            String timestamp = LocalDateTime.now().format(LOG_TIME_FORMAT);
            logArea.append("[" + timestamp + "] " + message + "\n");
            logArea.setCaretPosition(logArea.getDocument().getLength());
        }

        private void showError(String message) {
            JOptionPane.showMessageDialog(this, message, "错误", JOptionPane.ERROR_MESSAGE);
        }

        private void registerActionButton(JButton button) {
            actionButtons.add(button);
        }

        private void setActionButtonsEnabled(boolean enabled) {
            for (JButton actionButton : actionButtons) {
                actionButton.setEnabled(enabled);
            }
        }
    }

    private static final class Holder<T> {
        private T value;
    }
}
