package com.localengine.gui;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.localengine.document.DocType;
import com.localengine.document.Document;
import com.localengine.highlight.HighlightSpan;
import com.localengine.highlight.Snippet;
import com.localengine.index.IndexStatus;
import com.localengine.query.SearchHit;
import com.localengine.query.SearchResult;
import java.awt.GraphicsEnvironment;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.nio.file.Path;
import java.time.Instant;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.JButton;
import javax.swing.JFrame;
import javax.swing.JLabel;
import javax.swing.JTextArea;
import javax.swing.JTextField;
import javax.swing.JTextPane;
import javax.swing.SwingUtilities;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

class DesktopAppMainFrameTest {

    @Test
    void testMainFrameUtilitiesAndRendering() throws Exception {
        Assumptions.assumeFalse(GraphicsEnvironment.isHeadless());

        Object frame = createMainFrame();
        try {
            setTextField(frame, "indexDirField", " ./index ");
            setTextArea(frame, "sourcePathsArea", "docs\n./src");

            @SuppressWarnings("unchecked")
            List<Path> sourcePaths = (List<Path>) invokePrivate(frame, "parseSourcePaths", new Class<?>[] {});
            assertEquals(List.of(Path.of("docs"), Path.of("./src")), sourcePaths);

            Path resolvedIndexDir = (Path) invokePrivate(frame, "resolveIndexDir", new Class<?>[] {});
            assertEquals(Path.of("./index"), resolvedIndexDir);

            int threads = (Integer) invokePrivate(frame, "resolveThreads", new Class<?>[] {});
            assertTrue(threads >= 1);

            assertEquals("2.00 KB", invokePrivate(frame, "formatBytes", new Class<?>[] {long.class}, 2048L));
            assertEquals("x", invokePrivate(frame, "stripAnsi", new Class<?>[] {String.class}, "\u001B[31mx\u001B[0m"));
            assertEquals("filename:\"a\\\\b\\\"c\"",
                invokePrivate(frame, "toFileNameQuery", new Class<?>[] {String.class}, "a\\b\"c"));

            invokePrivate(frame, "applyStatus", new Class<?>[] {IndexStatus.class}, new IndexStatus(3, 4, 2, 4096));
            JLabel docCountLabel = (JLabel) readField(frame, "docCountLabel");
            JLabel termCountLabel = (JLabel) readField(frame, "termCountLabel");
            JLabel segmentCountLabel = (JLabel) readField(frame, "segmentCountLabel");
            JLabel indexSizeLabel = (JLabel) readField(frame, "indexSizeLabel");
            assertEquals("3", docCountLabel.getText());
            assertEquals("4", termCountLabel.getText());
            assertEquals("2", segmentCountLabel.getText());
            assertEquals("4.00 KB", indexSizeLabel.getText());

            Document document = new Document(1, Path.of("docs/demo.md"), "md", 64, Instant.now(), DocType.DOC, 7);
            Snippet snippet = new Snippet("hello world", 1, 0, List.of(new HighlightSpan(0, 5)));
            SearchHit hit = new SearchHit(document, 1.0, List.of(snippet));
            invokePrivate(frame,
                "renderSearchResult",
                new Class<?>[] {SearchResult.class},
                new SearchResult(List.of(hit), 1, 9, "hello"));

            JTextPane resultPane = (JTextPane) readField(frame, "searchResultPane");
            assertTrue(resultPane.getText().contains("demo.md"));

            invokePrivate(frame,
                "renderSearchResult",
                new Class<?>[] {SearchResult.class},
                new SearchResult(List.of(), 0, 1, "none"));
            assertTrue(resultPane.getText().contains("未找到匹配结果"));
        } finally {
            disposeFrame(frame);
        }
    }

    @Test
    void testMainFrameButtonRegistration() throws Exception {
        Assumptions.assumeFalse(GraphicsEnvironment.isHeadless());

        Object frame = createMainFrame();
        try {
            JButton button = new JButton("extra");
            invokePrivate(frame, "registerActionButton", new Class<?>[] {JButton.class}, button);
            invokePrivate(frame, "setActionButtonsEnabled", new Class<?>[] {boolean.class}, false);
            assertTrue(!button.isEnabled());
            invokePrivate(frame, "setActionButtonsEnabled", new Class<?>[] {boolean.class}, true);
            assertTrue(button.isEnabled());
        } finally {
            disposeFrame(frame);
        }
    }

    private static Object createMainFrame() throws Exception {
        AtomicReference<Object> ref = new AtomicReference<>();
        AtomicReference<Throwable> error = new AtomicReference<>();
        SwingUtilities.invokeAndWait(() -> {
            try {
                Class<?> frameClass = Class.forName("com.localengine.gui.DesktopApp$MainFrame");
                var constructor = frameClass.getDeclaredConstructor();
                constructor.setAccessible(true);
                ref.set(constructor.newInstance());
            } catch (Throwable throwable) {
                error.set(throwable);
            }
        });
        if (error.get() != null) {
            throw new RuntimeException(error.get());
        }
        return ref.get();
    }

    private static void disposeFrame(Object frame) throws Exception {
        SwingUtilities.invokeAndWait(() -> ((JFrame) frame).dispose());
    }

    private static void setTextField(Object frame, String fieldName, String value) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            try {
                JTextField field = (JTextField) readField(frame, fieldName);
                field.setText(value);
            } catch (Exception exception) {
                throw new RuntimeException(exception);
            }
        });
    }

    private static void setTextArea(Object frame, String fieldName, String value) throws Exception {
        SwingUtilities.invokeAndWait(() -> {
            try {
                JTextArea area = (JTextArea) readField(frame, fieldName);
                area.setText(value);
            } catch (Exception exception) {
                throw new RuntimeException(exception);
            }
        });
    }

    private static Object invokePrivate(Object target, String methodName, Class<?>[] parameterTypes, Object... args)
        throws Exception {
        Method method = target.getClass().getDeclaredMethod(methodName, parameterTypes);
        method.setAccessible(true);
        return method.invoke(target, args);
    }

    private static Object readField(Object target, String fieldName) throws Exception {
        Field field = target.getClass().getDeclaredField(fieldName);
        field.setAccessible(true);
        return field.get(target);
    }
}
